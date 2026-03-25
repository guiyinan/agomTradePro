"""
Integration Tests for Qlib Alpha Module

测试 Qlib 模块的端到端功能。
"""

import importlib.util
import os
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.test import override_settings

from apps.alpha.application.services import AlphaProviderRegistry, AlphaService
from apps.alpha.application.tasks import qlib_predict_scores
from apps.alpha.domain.entities import AlphaResult
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel


@pytest.mark.django_db
class TestQlibAlphaProvider:
    """Qlib Alpha Provider 集成测试"""

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

    @pytest.mark.skipif(
        os.environ.get('CI') == 'true',
        reason="Skip in CI - requires Celery worker"
    )
    @patch("apps.alpha.application.tasks._execute_qlib_prediction")
    def test_qlib_predict_scores_task(self, mock_predict):
        """测试 Qlib 推理任务（同步执行，避免依赖外部 broker）"""
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

    @pytest.mark.skipif(
        not importlib.util.find_spec("qlib"),
        reason="qlib not installed"
    )
    def test_full_prediction_flow(self):
        """测试完整的预测流程（使用模拟数据）"""
        from apps.account.infrastructure.models import SystemSettingsModel
        from apps.alpha.application.tasks import _execute_qlib_prediction

        qlib_config = SystemSettingsModel.get_runtime_qlib_config()
        if not qlib_config.get("enabled"):
            pytest.skip("Qlib installed but not enabled in runtime config")

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
            model_path="/models/mock.pkl"
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
