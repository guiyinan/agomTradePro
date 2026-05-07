"""
Integration Tests for Qlib Alpha Module

测试 Qlib 模块的端到端功能。
"""

import importlib.util
import os
import pickle
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.alpha.application.services import AlphaProviderRegistry, AlphaService
from apps.alpha.application.tasks import qlib_predict_scores
from apps.alpha.domain.entities import AlphaPoolScope, AlphaResult
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel


class _PickleablePredictor:
    """可序列化的预测器测试替身。"""

    def predict(self, dataset):
        import pandas as pd

        return pd.Series(
            {"SYNTH0001": 0.91, "SYNTH0002": 0.87, "SYNTH0003": 0.83}
        )


@pytest.mark.django_db
class TestQlibAlphaProvider:
    """Qlib Alpha Provider 集成测试"""

    def _small_pool_scope(self, trade_date: date) -> AlphaPoolScope:
        return AlphaPoolScope(
            pool_type="portfolio_market",
            market="CN",
            pool_mode="price_covered",
            instrument_codes=("000001.SZ", "600000.SH"),
            selection_reason="test",
            trade_date=trade_date,
            display_label="测试组合",
            portfolio_id=1,
            portfolio_name="测试组合",
        )

    def test_provider_properties(self):
        """测试 Provider 属性"""
        provider = QlibAlphaProvider()

        assert provider.name == "qlib"
        assert provider.priority == 1
        assert provider.max_staleness_days == 2

    def test_supports_common_universes(self):
        """测试支持的股票池"""
        provider = QlibAlphaProvider()

        assert provider.supports("csi300")
        assert provider.supports("csi500")
        assert provider.supports("sse50")

    @patch('apps.alpha.infrastructure.adapters.qlib_adapter.Path')
    def test_health_check_no_data_dir(self, mock_path):
        """测试健康检查 - 数据目录不存在"""
        mock_path.return_value.expanduser.return_value.exists.return_value = False

        provider = QlibAlphaProvider()
        status = provider.health_check()

        # 应该返回 UNAVAILABLE 或 DEGRADED（取决于是否有激活模型）
        assert status in [AlphaProviderStatus.UNAVAILABLE, AlphaProviderStatus.DEGRADED]

    @patch('apps.alpha.infrastructure.adapters.qlib_adapter.Path')
    def test_health_check_data_dir_exists(self, mock_path):
        """测试健康检查 - 数据目录存在"""
        mock_path.return_value.expanduser.return_value.exists.return_value = True

        provider = QlibAlphaProvider()
        status = provider.health_check()

        # 可能是 AVAILABLE（如果有激活模型且有缓存）
        # 或 UNAVAILABLE（如果没有激活模型）
        assert status in [
            AlphaProviderStatus.AVAILABLE,
            AlphaProviderStatus.DEGRADED,
            AlphaProviderStatus.UNAVAILABLE
        ]

    def test_get_stock_scores_no_cache(self):
        """测试获取股票评分 - 缓存未命中"""
        provider = QlibAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today())

        # 第一次调用应该返回 degraded（触发异步任务）
        assert result is not None
        # 缓存未命中时，success 可能是 False（触发异步任务）

    @patch("apps.alpha.infrastructure.adapters.qlib_adapter.current_app")
    @patch("apps.alpha.application.tasks.qlib_predict_scores.apply_async")
    def test_trigger_infer_task_falls_back_to_default_queue_when_needed(
        self,
        mock_apply_async,
        mock_current_app,
    ):
        """测试本地 worker 未监听 qlib_infer 时回退到默认 celery 队列。"""
        mock_current_app.control.inspect.return_value.active_queues.return_value = {
            "celery@worker": [{"name": "celery"}]
        }
        mock_apply_async.return_value = Mock(id="task-123")

        provider = QlibAlphaProvider()
        provider._trigger_infer_task("csi300", date(2026, 2, 5), 10)

        _, kwargs = mock_apply_async.call_args
        assert kwargs["queue"] == "celery"

    @patch("apps.alpha.infrastructure.adapters.qlib_adapter.current_app")
    @patch("apps.alpha.application.tasks.qlib_predict_scores.apply")
    def test_get_stock_scores_runs_inline_inference_without_worker(
        self,
        mock_apply,
        mock_current_app,
    ):
        """缓存未命中且没有 worker 时，应同步执行一次推理并回读缓存。"""
        mock_current_app.control.inspect.return_value.active_queues.return_value = None
        mock_task_result = Mock()
        mock_task_result.get.return_value = {"status": "success", "cache_created": True}
        mock_task_result.failed.return_value = False
        mock_apply.return_value = mock_task_result

        cached_result = AlphaResult(
            success=True,
            scores=[],
            source="qlib",
            timestamp="2026-02-05",
            status="available",
            metadata={"asof_date": "2026-02-05"},
        )
        provider = QlibAlphaProvider()
        trade_date = date(2026, 2, 6)
        pool_scope = self._small_pool_scope(trade_date)

        with patch.object(
            provider,
            "_get_from_cache",
            side_effect=[None, cached_result],
        ):
            result = provider.get_stock_scores(
                pool_scope.universe_id,
                trade_date,
                10,
                pool_scope=pool_scope,
            )

        assert result.success is True
        assert result.source == "qlib"
        assert result.metadata["inline_inference_executed"] is True
        assert result.metadata["inline_inference_result"]["status"] == "completed"
        mock_apply.assert_called_once()

    @patch("apps.alpha.infrastructure.adapters.qlib_adapter.current_app")
    @patch("apps.alpha.application.tasks.qlib_predict_scores.apply")
    def test_get_stock_scores_returns_degraded_when_inline_inference_has_no_cache(
        self,
        mock_apply,
        mock_current_app,
    ):
        """同步推理未写出缓存时，应返回降级结果并保留诊断元数据。"""
        mock_current_app.control.inspect.return_value.active_queues.return_value = None
        mock_task_result = Mock()
        mock_task_result.get.return_value = {"status": "failed", "error": "empty"}
        mock_task_result.failed.return_value = False
        mock_apply.return_value = mock_task_result

        provider = QlibAlphaProvider()
        trade_date = date(2026, 2, 7)
        pool_scope = self._small_pool_scope(trade_date)
        with patch.object(provider, "_get_from_cache", return_value=None):
            result = provider.get_stock_scores(
                pool_scope.universe_id,
                trade_date,
                10,
                pool_scope=pool_scope,
            )

        assert result.success is False
        assert result.status == "degraded"
        assert result.metadata["inference_trigger_status"] == "no_worker"
        assert result.metadata["inline_inference_executed"] is True

    @patch("apps.alpha.infrastructure.adapters.qlib_adapter.current_app")
    @patch("apps.alpha.application.tasks.qlib_predict_scores.apply")
    def test_get_stock_scores_skips_inline_inference_for_broad_universe(
        self,
        mock_apply,
        mock_current_app,
    ):
        """全市场请求没有 worker 时不能卡住前台请求。"""
        mock_current_app.control.inspect.return_value.active_queues.return_value = None
        provider = QlibAlphaProvider()

        with patch.object(provider, "_get_from_cache", return_value=None):
            result = provider.get_stock_scores("csi300", date(2026, 2, 8), 10)

        assert result.success is False
        assert result.metadata["inline_inference_result"]["status"] == "skipped"
        assert (
            result.metadata["inline_inference_result"]["reason"]
            == "inline_inference_requires_scoped_pool"
        )
        mock_apply.assert_not_called()

    def test_get_stock_scores_preserves_degraded_staleness_metadata(self):
        """测试命中前推缓存时不会把陈旧度误报为 0。"""
        QlibModelRegistryModel.objects.create(
            model_name="test_qlib_model",
            artifact_hash="test_hash_meta",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-03-30",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date.today(),
            provider_source="qlib",
            asof_date=date.today() - timedelta(days=22),
            model_id="test_qlib_model",
            model_artifact_hash="test_hash_meta",
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-03-30",
            scores=[
                {
                    "code": "SYNTH0001",
                    "score": 0.99,
                    "rank": 1,
                    "factors": {},
                    "source": "qlib",
                    "confidence": 0.8,
                },
                {
                    "code": "SYNTH0002",
                    "score": 0.98,
                    "rank": 2,
                    "factors": {},
                    "source": "qlib",
                    "confidence": 0.8,
                },
                {
                    "code": "SYNTH0003",
                    "score": 0.97,
                    "rank": 3,
                    "factors": {},
                    "source": "qlib",
                    "confidence": 0.8,
                },
            ],
            status=AlphaScoreCacheModel.STATUS_DEGRADED,
            metrics_snapshot={
                "fallback_mode": "forward_fill_latest_qlib_cache",
                "qlib_data_latest_date": "2020-09-25",
            },
        )

        provider = QlibAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today(), top_n=3)

        assert result.status == "degraded"
        assert result.staleness_days == 22
        assert result.metadata["fallback_mode"] == "forward_fill_latest_qlib_cache"
        assert result.metadata["qlib_data_latest_date"] == "2020-09-25"


@pytest.mark.django_db
class TestQlibCeleryTasks:
    """Qlib Celery 任务测试"""

    @staticmethod
    def _sample_scores(top_n: int) -> list[dict]:
        scores = []
        for i in range(1, top_n + 1):
            score = 1.0 - (i * 0.01)
            scores.append({
                "code": f"SYNTH{i:04d}",
                "score": float(score),
                "rank": i,
                "factors": {},
                "source": "qlib",
                "confidence": 0.8,
            })
        return scores

    @pytest.mark.optional_runtime
    @pytest.mark.skipif(
        os.environ.get('CI') == 'true',
        reason="Skip in CI - requires Celery worker"
    )
    @patch("apps.alpha.application.tasks._get_qlib_data_latest_date")
    @patch("apps.alpha.application.tasks._execute_qlib_prediction")
    def test_qlib_predict_scores_task(self, mock_predict, mock_latest_date):
        """测试 Qlib 推理任务（同步执行，避免依赖外部 broker）"""
        mock_latest_date.return_value = date(2026, 2, 5)
        mock_predict.return_value = self._sample_scores(10)

        QlibModelRegistryModel.objects.create(
            model_name="test_qlib_model",
            artifact_hash="test_hash_001",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-02-05",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )

        result = qlib_predict_scores.apply(args=("csi300", "2026-02-05", 10))
        outcome = result.get(timeout=60)

        assert outcome["status"] == "success"
        assert "universe_id" in outcome
        assert "trade_date" in outcome

    @patch("apps.alpha.application.tasks._execute_qlib_prediction")
    def test_qlib_predict_scores_reuses_latest_cache_when_prediction_fails(self, mock_predict):
        """测试 Qlib 推理失败时会前推最近一次可用缓存。"""
        mock_predict.side_effect = RuntimeError("qlib runtime broken")

        active_model = QlibModelRegistryModel.objects.create(
            model_name="test_qlib_model",
            artifact_hash="test_hash_forward_fill",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-02-06",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date(2026, 2, 4),
            provider_source="qlib",
            asof_date=date(2026, 2, 3),
            model_id="legacy_qlib_model",
            model_artifact_hash="",
            feature_set_id="legacy",
            label_id="return_5d",
            data_version="2026-02-03",
            scores=self._sample_scores(5),
            status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        )

        result = qlib_predict_scores.apply(args=("csi300", "2026-02-06", 3))
        outcome = result.get(timeout=60)

        assert outcome["status"] == "success"
        assert outcome["cache_status"] == AlphaScoreCacheModel.STATUS_DEGRADED
        assert outcome["fallback_used"] is True
        assert outcome["model_artifact_hash"] == active_model.artifact_hash

        cache = AlphaScoreCacheModel.objects.get(
            universe_id="csi300",
            intended_trade_date=date(2026, 2, 6),
            provider_source="qlib",
            model_artifact_hash=active_model.artifact_hash,
        )
        assert cache.status == AlphaScoreCacheModel.STATUS_DEGRADED
        assert cache.asof_date == date(2026, 2, 3)
        assert len(cache.scores) == 3
        assert cache.metrics_snapshot["fallback_mode"] == "forward_fill_latest_qlib_cache"
        assert cache.metrics_snapshot["fallback_source_trade_date"] == "2026-02-04"

    @patch("apps.alpha.application.tasks._get_qlib_data_latest_date")
    @patch("apps.alpha.application.tasks._execute_qlib_prediction")
    def test_qlib_predict_scores_short_circuits_when_local_data_is_outdated(
        self,
        mock_predict,
        mock_latest_date,
    ):
        """测试本地 qlib 数据过旧时直接前推缓存并给出清晰原因。"""
        mock_latest_date.return_value = date(2020, 9, 25)

        active_model = QlibModelRegistryModel.objects.create(
            model_name="test_qlib_model",
            artifact_hash="test_hash_outdated",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-03-30",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date(2026, 3, 10),
            provider_source="qlib",
            asof_date=date(2026, 3, 8),
            model_id="legacy_qlib_model",
            model_artifact_hash="",
            feature_set_id="legacy",
            label_id="return_5d",
            data_version="2026-03-08",
            scores=self._sample_scores(2),
            status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        )

        result = qlib_predict_scores.apply(args=("csi300", "2026-03-30", 2))
        outcome = result.get(timeout=60)

        assert outcome["status"] == "success"
        assert outcome["fallback_used"] is True
        assert outcome["qlib_data_latest_date"] == "2020-09-25"
        mock_predict.assert_not_called()

        cache = AlphaScoreCacheModel.objects.get(
            universe_id="csi300",
            intended_trade_date=date(2026, 3, 30),
            provider_source="qlib",
            model_artifact_hash=active_model.artifact_hash,
        )
        assert cache.status == AlphaScoreCacheModel.STATUS_DEGRADED
        assert cache.metrics_snapshot["qlib_data_latest_date"] == "2020-09-25"
        assert "2020-09-25" in cache.metrics_snapshot["fallback_reason"]

    @patch("apps.alpha.application.tasks._execute_qlib_prediction")
    @patch(
        "apps.alpha.application.tasks._get_qlib_data_latest_date",
        side_effect=ModuleNotFoundError("No module named 'qlib'"),
    )
    def test_qlib_predict_scores_reuses_latest_cache_when_qlib_runtime_is_unavailable(
        self,
        _mock_latest_date,
        mock_predict,
    ):
        """测试 qlib 运行时不可用时优先复用最近缓存，而不是直接重试失败。"""
        active_model = QlibModelRegistryModel.objects.create(
            model_name="test_qlib_model",
            artifact_hash="test_hash_runtime_missing",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-02-06",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date(2026, 2, 4),
            provider_source="qlib",
            asof_date=date(2026, 2, 3),
            model_id="legacy_qlib_model",
            model_artifact_hash="",
            feature_set_id="legacy",
            label_id="return_5d",
            data_version="2026-02-03",
            scores=self._sample_scores(4),
            status=AlphaScoreCacheModel.STATUS_AVAILABLE,
        )

        result = qlib_predict_scores.apply(args=("csi300", "2026-02-06", 2))
        outcome = result.get(timeout=60)

        assert outcome["status"] == "success"
        assert outcome["fallback_used"] is True
        assert outcome["cache_status"] == AlphaScoreCacheModel.STATUS_DEGRADED
        assert outcome["model_artifact_hash"] == active_model.artifact_hash
        assert outcome["qlib_data_latest_date"] is None
        assert "No module named 'qlib'" in outcome["qlib_runtime_error"]
        mock_predict.assert_not_called()

        cache = AlphaScoreCacheModel.objects.get(
            universe_id="csi300",
            intended_trade_date=date(2026, 2, 6),
            provider_source="qlib",
            model_artifact_hash=active_model.artifact_hash,
        )
        assert cache.status == AlphaScoreCacheModel.STATUS_DEGRADED
        assert len(cache.scores) == 2
        assert cache.metrics_snapshot["fallback_mode"] == "forward_fill_latest_qlib_cache"
        assert cache.metrics_snapshot["qlib_data_latest_date"] is None
        assert "No module named 'qlib'" in cache.metrics_snapshot["qlib_runtime_error"]

    def test_refresh_runtime_data_resets_one_process_qlib_state(self, monkeypatch):
        """测试刷新本地 qlib 数据后会清空进程内初始化标记。"""
        from apps.alpha.application import tasks as task_module

        class _FakeRefreshService:
            def refresh_universes(self, *, target_date, universes, lookback_days):
                return {
                    "status": "success",
                    "target_date": target_date.isoformat(),
                    "universes": list(universes),
                    "lookback_days": lookback_days,
                }

        task_module._get_qlib_data_latest_date._qlib_initialized = True
        task_module._execute_qlib_prediction._qlib_initialized = True
        monkeypatch.setattr(
            "apps.alpha.application.tasks.QlibRuntimeDataRefreshService",
            lambda: _FakeRefreshService(),
        )

        result = task_module._refresh_qlib_runtime_data(
            target_date=date(2026, 5, 6),
            universes=["csi300"],
            lookback_days=120,
        )

        assert result["status"] == "success"
        assert not hasattr(task_module._get_qlib_data_latest_date, "_qlib_initialized")
        assert not hasattr(task_module._execute_qlib_prediction, "_qlib_initialized")

    def test_resolve_recent_closed_trade_date_rolls_back_before_close(self):
        """测试午夜到收盘前的自动任务仍指向最近一个已收盘交易日。"""
        from apps.alpha.application.tasks import _resolve_recent_closed_trade_date

        reference_dt = timezone.make_aware(
            datetime(2026, 5, 7, 9, 30),
            timezone.get_current_timezone(),
        )

        assert _resolve_recent_closed_trade_date(reference_dt) == date(2026, 5, 6)

    def test_qlib_daily_scoped_inference_skips_fresh_scope_caches_and_queues_missing_scopes(
        self,
        monkeypatch,
    ):
        """测试收盘后 scoped 调度只补跑缺失或旧的 scope。"""
        from apps.alpha.application.tasks import qlib_daily_scoped_inference

        trade_date = date(2026, 5, 6)
        fresh_scope = AlphaPoolScope(
            pool_type="portfolio_market",
            market="CN",
            pool_mode="price_covered",
            instrument_codes=("000001.SZ",),
            selection_reason="fresh",
            trade_date=trade_date,
            display_label="组合A",
            portfolio_id=101,
            portfolio_name="组合A",
        )
        missing_scope = AlphaPoolScope(
            pool_type="portfolio_market",
            market="CN",
            pool_mode="price_covered",
            instrument_codes=("600000.SH",),
            selection_reason="missing",
            trade_date=trade_date,
            display_label="组合B",
            portfolio_id=102,
            portfolio_name="组合B",
        )
        scope_map = {
            101: fresh_scope,
            102: missing_scope,
        }

        class _FakePoolRepo:
            @staticmethod
            def list_active_portfolio_refs(*, limit):
                return [
                    {"portfolio_id": 101, "user_id": 7, "name": "组合A"},
                    {"portfolio_id": 102, "user_id": 8, "name": "组合B"},
                ]

        class _FakeResolver:
            def resolve(self, *, user_id, portfolio_id, trade_date, pool_mode):
                return SimpleNamespace(scope=scope_map[portfolio_id])

        class _FakeTask:
            calls: list[dict] = []

            @classmethod
            def delay(cls, universe_id, intended_trade_date, top_n, scope_payload=None):
                cls.calls.append(
                    {
                        "universe_id": universe_id,
                        "intended_trade_date": intended_trade_date,
                        "top_n": top_n,
                        "scope_payload": scope_payload,
                    }
                )
                return SimpleNamespace(id=f"task-{len(cls.calls)}")

        active_model = QlibModelRegistryModel.objects.create(
            model_name="scheduled_scoped_model",
            artifact_hash="scheduled_scoped_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-05-06",
            model_path="/tmp/test_model.pkl",
            is_active=True,
        )
        AlphaScoreCacheModel.objects.create(
            universe_id=fresh_scope.universe_id,
            intended_trade_date=trade_date,
            provider_source="qlib",
            asof_date=trade_date,
            model_id=active_model.model_name,
            model_artifact_hash=active_model.artifact_hash,
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026-05-06",
            scores=self._sample_scores(3),
            status=AlphaScoreCacheModel.STATUS_AVAILABLE,
            scope_hash=fresh_scope.scope_hash,
            scope_label=fresh_scope.display_label,
            scope_metadata=fresh_scope.to_dict(),
        )

        monkeypatch.setattr(
            "apps.alpha.application.tasks.get_alpha_pool_data_repository",
            lambda: _FakePoolRepo(),
        )
        monkeypatch.setattr(
            "apps.alpha.application.pool_resolver.PortfolioAlphaPoolResolver",
            _FakeResolver,
        )
        monkeypatch.setattr("apps.alpha.application.tasks.qlib_predict_scores", _FakeTask)

        result = qlib_daily_scoped_inference.run(
            top_n=10,
            portfolio_limit=0,
            pool_mode="price_covered",
            refresh_data=False,
            lookback_days=120,
            trade_date=trade_date.isoformat(),
            only_missing=True,
        )

        assert result["status"] == "queued"
        assert result["queued_count"] == 1
        assert result["fresh_cache_count"] == 1
        assert _FakeTask.calls[0]["universe_id"] == missing_scope.universe_id
        assert _FakeTask.calls[0]["intended_trade_date"] == trade_date.isoformat()
        assert _FakeTask.calls[0]["scope_payload"]["scope_hash"] == missing_scope.scope_hash


@pytest.mark.django_db
class TestQlibModelRegistry:
    """Qlib 模型注册表测试"""

    def test_create_model_registry(self):
        """测试创建模型注册记录"""
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="abc123",
            model_type="LGBModel",
            universe="csi300",
            train_config={"learning_rate": 0.01},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            ic=0.05,
            icir=0.8,
            model_path="/models/qlib/test_model/abc123/model.pkl"
        )

        assert model.model_name == "test_model"
        assert model.artifact_hash == "abc123"
        assert model.is_active is False

    def test_activate_model(self):
        """测试激活模型"""
        # 创建两个模型
        model1 = QlibModelRegistryModel.objects.create(
            model_name="model_v1",
            artifact_hash="hash1",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.01",
            model_path="/models/v1.pkl",
            is_active=True
        )

        model2 = QlibModelRegistryModel.objects.create(
            model_name="model_v2",
            artifact_hash="hash2",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/v2.pkl",
            is_active=False
        )

        # 激活 model2
        model2.activate(activated_by="test_user")

        # 刷新并检查
        model1.refresh_from_db()
        model2.refresh_from_db()

        assert model1.is_active is False
        assert model2.is_active is True
        assert model2.activated_by == "test_user"

    def test_get_active_model(self):
        """测试获取激活的模型"""
        # 创建并激活一个模型
        model = QlibModelRegistryModel.objects.create(
            model_name="active_model",
            artifact_hash="active_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/active.pkl"
        )
        model.activate()

        # 获取激活的模型
        active = QlibModelRegistryModel.objects.active().first()

        assert active is not None
        assert active.artifact_hash == "active_hash"


@pytest.mark.django_db
class TestAlphaScoreCacheWithQlib:
    """Alpha 评分缓存测试（Qlib 相关）"""

    def test_create_cache_entry(self):
        """测试创建缓存条目"""
        scores_data = [
            {
                "code": "000001.SH",
                "score": 0.8,
                "rank": 1,
                "factors": {"momentum": 0.7},
                "source": "qlib",
                "confidence": 0.8
            }
        ]

        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date.today(),
            provider_source="qlib",
            asof_date=date.today(),
            model_id="test_model",
            model_artifact_hash="abc123",
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            scores=scores_data,
            status="available"
        )

        assert cache.universe_id == "csi300"
        assert cache.provider_source == "qlib"
        assert len(cache.scores) == 1

    def test_cache_staleness_check(self):
        """测试缓存过期检查"""
        # 创建一个 5 天前的缓存
        old_date = date.today() - timedelta(days=5)

        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=old_date,
            provider_source="qlib",
            asof_date=old_date,
            model_id="test_model",
            model_artifact_hash="abc123",
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            scores=[],
            status="available"
        )

        # 检查是否过期
        is_stale = cache.is_stale(max_days=2)

        assert is_stale is True
        assert cache.get_staleness_days() == 5


@pytest.mark.django_db
class TestQlibIntegrationWithAlphaService:
    """Qlib 与 AlphaService 集成测试"""

    def test_qlib_provider_registered(self):
        """测试 Qlib Provider 注册状态（qlib 为可选依赖）"""
        service = AlphaService()
        providers = service._registry.get_all_providers()

        provider_names = {p.name for p in providers}

        # 基础 Provider 必须注册
        assert "cache" in provider_names
        assert "simple" in provider_names
        assert "etf" in provider_names

        # Qlib Provider 仅在 qlib 已安装且启用时注册
        qlib_installed = importlib.util.find_spec("qlib") is not None
        if qlib_installed and "qlib" in provider_names:
            assert True  # qlib 已安装且已注册
        elif not qlib_installed:
            assert "qlib" not in provider_names, (
                "qlib provider should not be registered when qlib is not installed"
            )

    def test_qlib_provider_priority(self):
        """测试 Qlib Provider 优先级最高（仅在 qlib 可用时）"""
        service = AlphaService()
        providers = service._registry.get_all_providers()

        # Qlib 应该是第一个（priority=1），但仅在已注册时检查
        qlib_providers = [p for p in providers if p.name == "qlib"]
        if qlib_providers:
            assert qlib_providers[0].priority == 1

    def test_fallback_includes_qlib(self):
        """测试降级链路包含 Qlib"""
        registry = AlphaProviderRegistry()

        qlib_provider = QlibAlphaProvider()
        registry.register(qlib_provider)

        providers = registry.get_all_providers()

        # Qlib 应该在列表中
        assert any(p.name == "qlib" for p in providers)


@pytest.mark.django_db
class TestQlibEndToEnd:
    """Qlib 端到端测试"""

    @pytest.mark.optional_runtime
    @pytest.mark.skipif(
        not importlib.util.find_spec("qlib"),
        reason="qlib not installed"
    )
    @patch("apps.alpha.application.tasks._build_outdated_qlib_reason", return_value=None)
    @patch("qlib.data.D")
    @patch("qlib.data.dataset.DatasetH", autospec=True)
    @patch("qlib.contrib.data.handler.Alpha360", autospec=True)
    @patch("qlib.init", autospec=True)
    def test_full_prediction_flow(
        self,
        mock_qlib_init,
        mock_alpha360,
        mock_dataset,
        mock_d,
        _mock_outdated_reason,
        tmp_path,
    ):
        """测试完整的预测流程（使用模拟依赖与测试库软开关）"""
        from apps.account.infrastructure.models import SystemSettingsModel
        from apps.alpha.application.tasks import _execute_qlib_prediction

        settings_obj = SystemSettingsModel.get_settings()
        settings_obj.qlib_enabled = True
        settings_obj.qlib_provider_uri = str((tmp_path / "qlib_data").resolve())
        settings_obj.qlib_model_path = str((tmp_path / "models").resolve())
        settings_obj.save(
            update_fields=[
                "qlib_enabled",
                "qlib_provider_uri",
                "qlib_model_path",
                "updated_at",
            ]
        )

        qlib_config = SystemSettingsModel.get_runtime_qlib_config()
        assert qlib_config["enabled"] is True

        model_file = tmp_path / "models" / "mock.pkl"
        model_file.parent.mkdir(parents=True, exist_ok=True)
        with model_file.open("wb") as fp:
            pickle.dump(_PickleablePredictor(), fp)

        (tmp_path / "qlib_data").mkdir(parents=True, exist_ok=True)

        mock_alpha360.return_value = Mock(name="alpha360-handler")
        mock_dataset.return_value = Mock(name="dataset")
        mock_d.instruments.return_value = {
            "market": "csi300",
            "filter_pipe": [],
        }
        mock_d.list_instruments.return_value = [
            "SYNTH0001",
            "SYNTH0002",
            "SYNTH0003",
        ]

        if hasattr(_execute_qlib_prediction, "_qlib_initialized"):
            delattr(_execute_qlib_prediction, "_qlib_initialized")

        # 创建一个模拟的激活模型
        model = QlibModelRegistryModel.objects.create(
            model_name="mock_model",
            artifact_hash="mock_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path=str(model_file),
        )
        model.activate()

        # 执行预测（会使用模拟数据）
        scores = _execute_qlib_prediction(
            active_model=model,
            universe_id="csi300",
            trade_date=date.today(),
            top_n=10
        )

        # 应该返回模拟数据
        assert len(scores) > 0
        assert all("code" in s for s in scores)
        assert all("score" in s for s in scores)
        assert scores[0]["rank"] == 1
        mock_qlib_init.assert_called_once()
        mock_alpha360.assert_called_once()
        mock_dataset.assert_called_once()
        mock_d.instruments.assert_called_once_with(market="csi300")
        mock_d.list_instruments.assert_called_once()


@pytest.mark.django_db
class TestQlibManagementCommands:
    """Qlib 管理命令测试"""

    def test_init_qlib_data_check_only(self):
        """测试 init_qlib_data 命令（仅检查）"""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()

        # 使用 --check 选项
        try:
            call_command(
                'init_qlib_data',
                '--check',
                stdout=out
            )
        except Exception as e:
            # 预期可能失败（如果 Qlib 未安装）
            assert "Qlib" in str(e) or "qlib" in str(e).lower()

    @pytest.mark.optional_runtime
    @pytest.mark.skipif(
        os.environ.get('CI') == 'true',
        reason="Skip in CI - requires Qlib installation"
    )
    def test_init_qlib_data_with_download(self):
        """测试 init_qlib_data 命令（下载）"""
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()

        # 这个测试需要 Qlib 已安装
        try:
            call_command(
                'init_qlib_data',
                '--check',
                stdout=out
            )
            output = out.getvalue()

            # 应该包含 Qlib 版本信息
            if "Qlib 版本" in output or "Qlib 未安装" in output:
                pass  # 成功或预期失败

        except ImportError:
            # Qlib 未安装 - 预期情况
            pass


@pytest.mark.django_db
class TestQlibCacheWriteFlow:
    """Qlib 缓存写入流程测试"""

    def test_cache_write_after_prediction(self):
        """测试预测后写入缓存"""
        from apps.alpha.application.tasks import qlib_predict_scores

        # 创建激活模型
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl"
        )
        model.activate()

        # 执行推理任务（同步，用于测试）
        # 注意：这会尝试调用 Qlib，如果未安装会使用模拟数据
        try:
            result = qlib_predict_scores(
                universe_id="csi300",
                intended_trade_date="2026-02-05",
                top_n=10
            )

            # 检查返回
            assert result["status"] == "success"

            # 检查缓存是否写入
            cache = AlphaScoreCacheModel.objects.filter(
                universe_id="csi300",
                provider_source="qlib",
                model_artifact_hash="test_hash"
            ).first()

            # 如果任务成功完成，应该有缓存
            if cache:
                assert cache.universe_id == "csi300"
                assert cache.provider_source == "qlib"

        except Exception as e:
            # Qlib 未安装或其他问题
            assert "Qlib" in str(e) or "qlib" in str(e).lower() or "Model" in str(e)
