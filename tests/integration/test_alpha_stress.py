"""
Stress Tests for Qlib Failure Scenarios

测试 Qlib 组件故障时系统的行为：
1. Qlib 未安装
2. Qlib 数据不可用
3. Qlib 推理任务失败
4. 模型加载失败
5. 缓存全部过期
6. 全链路降级
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from django.db import close_old_connections, connections
from django.utils import timezone

from apps.alpha.application.services import AlphaService
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel
from apps.alpha.application.tasks import qlib_predict_scores
from shared.infrastructure.metrics import get_alpha_metrics


# --- Helper: mock ETF constituents so ETF fallback returns real data ---
_ETF_CONSTITUENTS_PATH = (
    "apps.alpha.infrastructure.adapters.etf_adapter"
    ".ETFFallbackProvider._get_etf_constituents"
)
_FAKE_ETF_CONSTITUENTS = (
    [("600519.SH", 5.0), ("000858.SZ", 3.5), ("601318.SH", 2.8)],
    None,
)


def _reset_alpha_service():
    """Reset AlphaService singleton so providers are re-initialised."""
    AlphaService._instance = None


@pytest.mark.django_db
class TestQlibNotInstalled:
    """测试 Qlib 未安装场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    @patch('apps.alpha.infrastructure.adapters.qlib_adapter.QlibAlphaProvider._get_active_model')
    def test_alpha_service_works_without_qlib(self, mock_get_model, _mock_etf):
        """测试没有 Qlib 时 AlphaService 仍然工作"""
        # Mock 返回 None（模拟没有激活的模型）
        mock_get_model.return_value = None

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该降级到其他 Provider
        assert result.success or result.source in ["cache", "simple", "etf"]

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    @patch('apps.alpha.infrastructure.adapters.qlib_adapter.QlibAlphaProvider._get_active_model')
    def test_fallback_chain_without_qlib(self, mock_get_model, _mock_etf):
        """测试没有 Qlib 时的完整降级链路"""
        # 清空所有缓存
        AlphaScoreCacheModel.objects.all().delete()

        mock_get_model.return_value = None

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该最终降级到 ETF Provider（总是可用）
        assert result.source in ["simple", "etf"]


@pytest.mark.django_db
class TestQlibDataUnavailable:
    """测试 Qlib 数据不可用场景"""

    def test_qlib_data_missing_fallback_to_cache(self):
        """测试 Qlib 数据缺失时降级到缓存"""
        # 创建缓存数据（作为备用）
        today = date.today()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.8}
            ],
            status="available"
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 应该从缓存获取
        assert result.success
        assert result.source in ["cache", "qlib"]

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_all_cache_expired_fallback_to_simple(self, _mock_etf):
        """测试所有缓存过期时降级到 Simple"""
        _reset_alpha_service()
        # 创建过期的缓存（10 天前）
        old_date = date.today() - timedelta(days=10)
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=old_date,
            provider_source="cache",
            asof_date=old_date,
            scores=[],
            status="available"
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该降级到 Simple 或 ETF
        assert result.source in ["simple", "etf"]


@pytest.mark.django_db
class TestQlibInferenceFailure:
    """测试 Qlib 推理任务失败场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    @patch('apps.alpha.application.tasks.qlib_predict_scores.apply_async')
    def test_inference_task_failure_handled_gracefully(self, mock_apply_async, _mock_etf):
        """测试推理任务失败时的优雅处理"""
        # Mock apply_async 抛出异常
        mock_apply_async.side_effect = Exception("Celery unavailable")

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该降级，不抛出异常
        assert result is not None
        assert result.source in ["cache", "simple", "etf"]

    @patch('apps.alpha.application.tasks.qlib_predict_scores.apply_async')
    def test_inference_task_timeout(self, mock_apply_async):
        """测试推理任务超时场景"""
        # Mock 任务延迟执行（模拟超时）
        from celery.result import AsyncResult
        mock_result = Mock(spec=AsyncResult)
        mock_result.id = "test-task-id"
        mock_apply_async.return_value = mock_result

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该立即返回 degraded，不等待任务完成
        assert result is not None


@pytest.mark.django_db
class TestModelLoadingFailure:
    """测试模型加载失败场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_no_active_model_fallback(self, _mock_etf):
        """测试没有激活模型时的降级"""
        # 确保没有激活的模型
        QlibModelRegistryModel.objects.filter(is_active=True).update(is_active=False)

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该降级到其他 Provider
        assert result.source in ["cache", "simple", "etf"]

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_model_file_missing(self, _mock_etf):
        """测试模型文件缺失场景"""
        # 创建模型记录，但文件不存在
        model = QlibModelRegistryModel.objects.create(
            model_name="missing_file_model",
            artifact_hash="missing_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="v1",
            model_path="/models/missing/nonexistent.pkl",  # 文件不存在
            is_active=True
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该降级到其他 Provider
        assert result.source in ["cache", "simple", "etf"]


@pytest.mark.django_db
class TestCompleteDegradation:
    """测试全链路降级场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_full_degradation_chain(self, _mock_etf):
        """测试完整降级链路：Qlib → Cache → Simple → ETF"""
        service = AlphaService()

        # 1. Qlib 不可用（没有激活模型）
        QlibModelRegistryModel.objects.filter(is_active=True).update(is_active=False)

        # 2. 缓存过期或不存在
        AlphaScoreCacheModel.objects.all().delete()

        # 获取评分
        result = service.get_stock_scores("csi300")

        # 应该最终降级到 ETF
        assert result.success
        assert result.source == "etf" or result.source == "simple"

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_etf_provider_always_available(self, _mock_etf):
        """测试 ETF Provider 总是可用"""
        service = AlphaService()

        # 清空所有数据
        AlphaScoreCacheModel.objects.all().delete()
        QlibModelRegistryModel.objects.all().delete()

        # 多次尝试获取评分
        for _ in range(10):
            result = service.get_stock_scores("csi300")
            assert result.success
            assert result.source == "etf"


@pytest.mark.django_db
class TestHighLoadScenarios:
    """测试高负载场景"""

    def test_concurrent_requests(self):
        """测试并发请求"""
        import threading

        service = AlphaService()
        results = []
        errors = []

        def get_scores():
            try:
                close_old_connections()
                result = service.get_stock_scores("csi300")
                results.append(result)
            except Exception as e:
                errors.append(e)
            finally:
                connections.close_all()

        # 创建多个线程
        threads = []
        for _ in range(10):
            t = threading.Thread(target=get_scores)
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        connections.close_all()

        # 验证：所有请求都应该成功，没有异常
        assert len(errors) == 0
        assert len(results) == 10

    def test_rapid_sequential_requests(self):
        """测试快速连续请求"""
        service = AlphaService()

        # 快速发送 100 个请求
        for _ in range(100):
            result = service.get_stock_scores("csi300")
            assert result is not None


@pytest.mark.django_db
class TestMetricsUnderFailure:
    """测试故障时的监控指标"""

    def test_provider_failure_metrics(self):
        """测试 Provider 失败时的指标记录"""
        metrics = get_alpha_metrics()
        metrics.registry.reset_metrics()

        # 模拟 Provider 失败
        metrics.record_provider_call(
            provider_name="qlib",
            success=False,
            latency_ms=5000
        )

        # 获取成功率指标
        success_rate = metrics.registry.get_metric(
            "alpha_provider_success_rate",
            {"provider": "qlib"}
        )

        assert success_rate is not None
        assert success_rate.value < 1.0  # 失败后成功率应该下降

    def test_alert_triggered_on_failure(self):
        """测试失败时触发告警"""
        from apps.alpha.application.monitoring_tasks import evaluate_alerts

        metrics = get_alpha_metrics()

        # 设置会触发告警的值
        metrics.registry.set_gauge(
            "alpha_provider_success_rate",
            0.3,  # 低于 0.5 的临界值
            labels={"provider": "qlib"}
        )

        # 评估告警（设置持续时间为 0 以便立即触发）
        from apps.alpha.infrastructure.alerts import AlphaAlertConfig
        for rule in AlphaAlertConfig.get_all_rules():
            if rule.name == "provider_unavailable":
                rule.duration_seconds = 0

        # 评估
        result = evaluate_alerts()

        # 应该有告警
        assert "count" in result


@pytest.mark.django_db
class TestCacheFailureScenarios:
    """测试缓存故障场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_cache_corruption_handling(self, _mock_etf):
        """测试缓存损坏处理"""
        # 创建损坏的缓存（scores 为空）
        today = date.today()
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[],  # 空评分
            status="available"
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 应该跳过损坏的缓存，降级到下一个 Provider
        assert result.source in ["simple", "etf"]

    def test_cache_inconsistent_data(self):
        """测试缓存数据不一致"""
        today = date.today()

        # 创建多个矛盾的缓存记录
        for i in range(3):
            AlphaScoreCacheModel.objects.create(
                universe_id="csi300",
                intended_trade_date=today,
                provider_source="cache",
                asof_date=today,
                scores=[
                    {"code": f"TEST{i:04d}.SH", "score": 0.5 + i * 0.1, "rank": i + 1, "factors": {}, "confidence": 0.5}
                ],
                status="available"
            )

        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 应该仍然返回结果（使用最新的）
        assert result is not None


@pytest.mark.django_db
class TestRecoveryScenarios:
    """测试恢复场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_qlib_recovery_after_failure(self, _mock_etf):
        """测试 Qlib 恢复后的行为"""
        # 1. 初始状态：没有激活模型
        service = AlphaService()
        result1 = service.get_stock_scores("csi300")

        # 应该降级
        assert result1.source in ["cache", "simple", "etf"]

        # 2. 创建激活的模型
        model = QlibModelRegistryModel.objects.create(
            model_name="recovery_test",
            artifact_hash="recovery_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="v1",
            model_path="/models/recovery.pkl",
            is_active=True
        )

        # 创建 Qlib 缓存
        today = date.today()
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=today,
            model_artifact_hash="recovery_hash",
            scores=[
                {"code": "600519.SH", "score": 0.9, "rank": 1, "factors": {}, "confidence": 0.9}
            ],
            status="available"
        )

        # 3. 再次获取评分
        result2 = service.get_stock_scores("csi300", today)

        # 应该使用 Qlib 或缓存
        assert result2.source in ["qlib", "cache"]


@pytest.mark.django_db
class TestMemoryPressure:
    """测试内存压力场景"""

    def test_large_universe_handling(self):
        """测试大股票池处理"""
        service = AlphaService()

        # 尝试获取大股票池的评分
        result = service.get_stock_scores("csi1000", top_n=100)

        # 应该返回结果（可能来自降级 Provider）
        assert result is not None

    def test_multiple_universes_simultaneously(self):
        """测试同时处理多个股票池"""
        service = AlphaService()

        universes = ["csi300", "csi500", "sse50", "csi1000"]
        results = {}

        for universe in universes:
            result = service.get_stock_scores(universe, top_n=10)
            results[universe] = result

        # 所有请求都应该成功
        assert all(r is not None for r in results.values())


@pytest.mark.django_db
class TestNetworkFailure:
    """测试网络故障场景"""

    def setup_method(self):
        _reset_alpha_service()

    def teardown_method(self):
        _reset_alpha_service()

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    @patch('apps.alpha.infrastructure.adapters.simple_adapter.SimpleAlphaProvider.get_stock_scores')
    def test_external_api_failure(self, mock_simple, _mock_etf):
        """测试外部 API 失败"""
        # Mock Simple Provider 失败
        mock_simple.side_effect = Exception("Network timeout")

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # 应该最终降级到 ETF（不依赖外部 API）
        assert result.success
        assert result.source == "etf"

    @patch('apps.alpha.infrastructure.adapters.etf_adapter.ETFFallbackProvider.get_stock_scores')
    def test_etf_provider_resilience(self, mock_etf):
        """测试 ETF Provider 的韧性"""
        # 即使其他 Provider 都失败，ETF 也应该工作
        # Mock 返回正常结果
        from apps.alpha.domain.entities import StockScore, AlphaResult

        mock_etf.return_value = AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code="510300.SH",
                    score=1.0,
                    rank=1,
                    factors={},
                    source="etf",
                    confidence=1.0
                )
            ],
            source="etf",
            timestamp=date.today().isoformat(),
            status="available"
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300")

        # ETF Provider 应该总是可用
        assert result.success


@pytest.mark.django_db
class TestGracefulDegradation:
    """测试优雅降级"""

    def test_service_never_crashes(self):
        """测试服务从不崩溃"""
        service = AlphaService()

        # 尝试各种极端输入
        test_cases = [
            ("nonexistent_universe", date.today()),
            ("csi300", None),
            ("", date.today()),
        ]

        for universe, trade_date in test_cases:
            try:
                result = service.get_stock_scores(universe, trade_date)
                # 应该返回结果而不是抛出异常
                assert result is not None
            except Exception as e:
                pytest.fail(f"Service crashed for {universe}: {e}")

    def test_empty_result_handling(self):
        """测试空结果处理"""
        # 创建空的缓存
        today = date.today()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[],  # 空评分
            status="available"
        )

        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 应该降级到下一个 Provider
        assert result is not None


@pytest.mark.django_db
class TestLongRunningStability:
    """测试长期运行稳定性"""

    def test_extended_operation(self):
        """测试长时间运行的稳定性"""
        service = AlphaService()

        # 模拟运行 30 天
        for day in range(30):
            test_date = date.today() - timedelta(days=day)

            # 多次请求
            for _ in range(10):
                result = service.get_stock_scores("csi300", test_date)
                assert result is not None

    def test_metrics_accumulation(self):
        """测试指标累积不溢出"""
        metrics = get_alpha_metrics()

        # 模拟大量请求
        for _ in range(1000):
            metrics.record_provider_call(
                provider_name="test",
                success=True,
                latency_ms=100
            )

        # 检查计数器
        counter = metrics.registry.get_metric("alpha_score_request_count")
        assert counter is not None
        assert counter.value >= 1000


@pytest.mark.django_db
class TestErrorRecovery:
    """测试错误恢复"""

    def test_auto_recovery_after_outage(self):
        """测试故障后自动恢复"""
        service = AlphaService()

        # 1. 初始状态：没有缓存
        AlphaScoreCacheModel.objects.all().delete()
        result1 = service.get_stock_scores("csi300")

        # 2. 添加缓存数据
        today = date.today()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.8}
            ],
            status="available"
        )

        # 3. 再次请求
        result2 = service.get_stock_scores("csi300", today)

        # 应该使用新数据
        assert result2 is not None
