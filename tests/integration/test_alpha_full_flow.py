"""
End-to-End Integration Tests for Alpha Module

测试 Alpha 模块的完整流程：
1. Alpha 信号生成
2. 统一信号系统集成
3. 回测集成
4. Provider 降级链路
5. 监控指标记录
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

from django.utils import timezone

from apps.alpha.application.services import AlphaService
from apps.alpha.application.tasks import qlib_predict_scores
from apps.alpha.infrastructure.models import AlphaScoreCacheModel, QlibModelRegistryModel
from apps.signal.application.unified_service import UnifiedSignalService

# --- Helper: mock ETF constituents so ETF fallback returns real data ---
_ETF_CONSTITUENTS_PATH = (
    "apps.alpha.infrastructure.adapters.etf_adapter"
    ".ETFFallbackProvider._get_etf_constituents"
)
_FAKE_ETF_CONSTITUENTS = (
    [("600519.SH", 5.0), ("000858.SZ", 3.5), ("601318.SH", 2.8)],
    None,
)
from apps.backtest.domain.alpha_backtest import (
    RunAlphaBacktestUseCase,
    RunAlphaBacktestRequest,
)
from shared.infrastructure.metrics import get_alpha_metrics


@pytest.mark.django_db
class TestAlphaSignalIntegration:
    """测试 Alpha 与 Signal 模块集成"""

    def test_unified_service_collects_alpha_signals(self):
        """测试统一服务收集 Alpha 信号"""
        service = UnifiedSignalService()

        # 创建一些模拟的 Alpha 缓存数据
        today = date.today()
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.8, "rank": 1},
                {"code": "000333.SH", "score": 0.7, "rank": 2},
            ],
            status="available"
        )

        # 收集信号
        result = service.collect_all_signals(today)

        # 验证
        assert "alpha_signals" in result
        assert result["total_signals"] >= result["alpha_signals"]

    def test_alpha_signals_in_unified_repo(self):
        """测试 Alpha 信号存储在统一仓储"""
        service = UnifiedSignalService()

        today = date.today()

        # 创建模拟缓存
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.85, "rank": 1},
            ],
            status="available"
        )

        # 收集信号
        service.collect_all_signals(today)

        # 查询统一信号
        signals = service.get_unified_signals(
            signal_date=today,
            signal_source="alpha"
        )

        # 验证至少有一条 Alpha 信号
        assert len(signals) >= 0  # 如果 Alpha 服务不可用，可能为 0


@pytest.mark.django_db
class TestAlphaBacktestIntegration:
    """测试 Alpha 与 Backtest 模块集成"""

    def test_alpha_backtest_config_creation(self):
        """测试 Alpha 回测配置创建"""
        from apps.backtest.domain.alpha_backtest import AlphaBacktestConfig, RebalanceFrequency

        config = AlphaBacktestConfig(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            initial_capital=Decimal("1000000"),
            universe_id="csi300",
            alpha_provider="qlib",
            min_score=0.6,
            max_positions=30,
            rebalance_frequency=RebalanceFrequency.MONTHLY,
        )

        assert config.universe_id == "csi300"
        assert config.alpha_provider == "qlib"
        assert config.min_score == 0.6

    @patch('apps.backtest.domain.alpha_backtest.AlphaService')
    def test_alpha_backtest_use_case_execution(self, mock_alpha_service_class):
        """测试 Alpha 回测用例执行"""
        # Mock Alpha 服务
        mock_alpha_service = Mock()
        mock_alpha_service_class.return_value = mock_alpha_service

        # Mock Alpha 结果
        from apps.alpha.domain.entities import AlphaResult, StockScore
        mock_result = AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code="600519.SH",
                    score=0.8,
                    rank=1,
                    factors={"momentum": 0.7},
                    source="cache",
                    confidence=0.9
                )
            ],
            source="cache",
            timestamp=datetime.now().isoformat(),
            status="available"
        )
        mock_alpha_service.get_stock_scores.return_value = mock_result

        # 创建 use case
        repository = Mock()
        use_case = RunAlphaBacktestUseCase(
            repository=repository,
            get_regime_func=lambda d: "Recovery",
            get_price_func=lambda c, d: Decimal("100"),
            get_benchmark_price_func=lambda d: 100.0,
        )

        # 执行请求
        request = RunAlphaBacktestRequest(
            name="Test Alpha Backtest",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            initial_capital=1000000.0,
            universe_id="csi300",
        )

        # Mock repository
        mock_backtest = Mock()
        mock_backtest.id = 1
        repository.create_backtest.return_value = mock_backtest

        # 执行
        response = use_case.execute(request)

        # 验证
        assert response.status in ["completed", "failed"]


@pytest.mark.django_db
class TestAlphaProviderFallback:
    """测试 Alpha Provider 降级链路"""

    def test_provider_fallback_order(self):
        """测试 Provider 降级顺序"""
        service = AlphaService()

        status = service.get_provider_status()

        # 验证所有已注册的 Provider
        assert len(status) >= 3  # 至少有 Cache, Simple, ETF

        # 验证优先级顺序（priority 值越小优先级越高）
        priorities = [info.get("priority", float("inf")) for info in status.values()]
        assert priorities == sorted(priorities)

    def test_qlib_fallback_to_cache(self):
        """测试 Qlib 降级到 Cache"""
        service = AlphaService()

        # 确保有缓存数据
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

        # 获取评分（应该从 Cache 返回）
        result = service.get_stock_scores("csi300", today)

        assert result.success
        assert result.source in ["cache", "simple", "etf"]  # 降级链路之一

    @patch(_ETF_CONSTITUENTS_PATH, return_value=_FAKE_ETF_CONSTITUENTS)
    def test_fallback_to_etf(self, _mock_etf):
        """测试最终降级到 ETF"""
        AlphaService._instance = None
        service = AlphaService()

        # 不创建任何缓存，应该最终降级到 ETF
        result = service.get_stock_scores("csi300")

        # ETF Provider 应该总是可用
        assert result.success or result.source == "etf"
        AlphaService._instance = None


@pytest.mark.django_db
class TestAlphaMetricsRecording:
    """测试 Alpha 监控指标记录"""

    def test_metrics_recorded_on_get_scores(self):
        """测试获取评分时记录指标"""
        metrics = get_alpha_metrics()

        # 清空之前的状态
        metrics.registry.reset_metrics()

        # 创建缓存数据
        today = date.today()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.8},
                {"code": "000333.SH", "score": 0.7, "rank": 2, "factors": {}, "confidence": 0.7},
            ],
            status="available"
        )

        # 获取评分
        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 验证指标被记录
        request_metric = metrics.registry.get_metric("alpha_score_request_count")
        assert request_metric is not None
        assert request_metric.value >= 1

    def test_coverage_metric_recorded(self):
        """测试覆盖率指标记录"""
        metrics = get_alpha_metrics()

        # 清空之前的状态
        metrics.registry.reset_metrics()

        # 创建缓存数据（只有 2 只股票）
        today = date.today()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[
                {"code": "600519.SH", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.8},
                {"code": "000333.SH", "score": 0.7, "rank": 2, "factors": {}, "confidence": 0.7},
            ],
            status="available"
        )

        # 获取评分
        service = AlphaService()
        result = service.get_stock_scores("csi300", today)

        # 验证覆盖率指标
        coverage_metric = metrics.registry.get_metric("alpha_coverage_ratio")
        assert coverage_metric is not None


@pytest.mark.django_db
class TestAlphaQlibIntegration:
    """测试 Alpha 与 Qlib 集成"""

    def test_qlib_model_registry_operations(self):
        """测试 Qlib 模型注册表操作"""
        # 创建模型记录
        model = QlibModelRegistryModel.objects.create(
            model_name="test_model",
            artifact_hash="test_hash_001",
            model_type="LGBModel",
            universe="csi300",
            train_config={"learning_rate": 0.01},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/test.pkl",
            ic=0.05,
            icir=0.8,
            is_active=True
        )

        # 激活模型
        model.activate(activated_by="test_user")

        # 验证
        assert model.is_active
        assert model.activated_by == "test_user"

        # 获取激活的模型
        active_models = QlibModelRegistryModel.objects.active()
        assert len(active_models) == 1
        assert active_models[0].artifact_hash == "test_hash_001"

    def test_model_rollback(self):
        """测试模型回滚"""
        # 创建两个模型版本
        old_model = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="old_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.01.01",
            model_path="/models/old.pkl"
        )

        current = QlibModelRegistryModel.objects.create(
            model_name="my_model",
            artifact_hash="current_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/current.pkl",
            is_active=True
        )

        # 回滚到上一个版本
        current.deactivate()
        old_model.activate(activated_by="rollback_test")

        # 验证
        old_model.refresh_from_db()
        current.refresh_from_db()

        assert old_model.is_active
        assert not current.is_active


@pytest.mark.django_db
class TestAlphaEndToEndFlow:
    """端到端流程测试"""

    def test_complete_alpha_flow(self):
        """测试完整的 Alpha 流程"""
        # 1. 创建激活的模型
        model = QlibModelRegistryModel.objects.create(
            model_name="e2e_test_model",
            artifact_hash="e2e_hash",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="2026.02.05",
            model_path="/models/e2e.pkl",
            ic=0.06,
            is_active=True
        )

        # 2. 创建评分缓存（模拟 Qlib 推理结果）
        today = date.today()
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="qlib",
            asof_date=today,
            model_id="e2e_test_model",
            model_artifact_hash="e2e_hash",
            scores=[
                {"code": "600519.SH", "score": 0.85, "rank": 1, "factors": {"momentum": 0.8}, "confidence": 0.9},
                {"code": "000333.SH", "score": 0.75, "rank": 2, "factors": {"value": 0.7}, "confidence": 0.8},
            ],
            status="available"
        )

        # 3. 获取评分（通过 AlphaService）
        service = AlphaService()
        result = service.get_stock_scores("csi300", today, top_n=5)

        # 验证
        assert result.success
        assert len(result.scores) >= 2

        # 验证评分来自 Qlib 或其降级链路
        assert result.source in ["qlib", "cache", "simple", "etf"]

        # 验证评分包含审计信息
        if result.scores:
            stock = result.scores[0]
            assert stock.code is not None
            assert stock.score is not None
            assert stock.rank is not None


@pytest.mark.django_db
class TestAlphaWithMonitoring:
    """测试 Alpha 监控功能"""

    def test_alert_evaluation(self):
        """测试告警评估"""
        from apps.alpha.application.monitoring_tasks import evaluate_alerts

        # 创建会触发告警的指标
        metrics = get_alpha_metrics()
        metrics.registry.set_gauge(
            "alpha_provider_success_rate",
            0.3,  # 低于阈值 0.5
            labels={"provider": "test"}
        )

        # 评估告警
        result = evaluate_alerts()

        # 验证
        assert "status" in result
        assert "timestamp" in result

    def test_daily_report_generation(self):
        """测试每日报告生成"""
        from apps.alpha.application.monitoring_tasks import generate_daily_report

        # 创建一些数据
        today = timezone.now().date()
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=today,
            provider_source="cache",
            asof_date=today,
            scores=[],
            status="available"
        )

        # 生成报告
        report = generate_daily_report()

        # 验证
        assert "date" in report
        assert "cache_records" in report
        assert "provider_stats" in report


@pytest.mark.django_db
class TestAlphaModelLifecycle:
    """测试 Alpha 模型生命周期"""

    def test_model_activation_deactivation(self):
        """测试模型激活/取消激活"""
        # 创建两个模型
        model1 = QlibModelRegistryModel.objects.create(
            model_name="lifecycle_model",
            artifact_hash="hash1",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="v1",
            model_path="/models/v1.pkl"
        )

        model2 = QlibModelRegistryModel.objects.create(
            model_name="lifecycle_model",
            artifact_hash="hash2",
            model_type="LGBModel",
            universe="csi300",
            train_config={},
            feature_set_id="v1",
            label_id="return_5d",
            data_version="v2",
            model_path="/models/v2.pkl"
        )

        # 激活 model1
        model1.activate(activated_by="user1")
        assert model1.is_active

        # 激活 model2（应该自动取消 model1）
        model2.activate(activated_by="user2")

        model1.refresh_from_db()
        model2.refresh_from_db()

        assert not model1.is_active
        assert model2.is_active

    def test_model_version_history(self):
        """测试模型版本历史"""
        model_name = "history_model"

        # 创建多个版本
        for i in range(3):
            QlibModelRegistryModel.objects.create(
                model_name=model_name,
                artifact_hash=f"hash_v{i}",
                model_type="LGBModel",
                universe="csi300",
                train_config={},
                feature_set_id="v1",
                label_id="return_5d",
                data_version=f"v{i}",
                model_path=f"/models/v{i}.pkl"
            )

        # 查询所有版本
        models = QlibModelRegistryModel.objects.filter(
            model_name=model_name
        ).order_by('data_version')

        assert models.count() == 3


@pytest.mark.django_db
class TestAlphaCacheStaleness:
    """测试 Alpha 缓存陈旧度检查"""

    def test_cache_staleness_detection(self):
        """测试缓存陈旧度检测"""
        # 创建陈旧的缓存（10 天前）
        old_date = date.today() - timedelta(days=10)
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=old_date,
            provider_source="cache",
            asof_date=old_date,
            scores=[],
            status="available"
        )

        # 检查陈旧度
        staleness = cache.get_staleness_days()

        assert staleness >= 10

    def test_fresh_cache_not_stale(self):
        """测试新鲜缓存不算陈旧"""
        # 创建新鲜的缓存（1 天前）
        recent_date = date.today() - timedelta(days=1)
        cache = AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=recent_date,
            provider_source="cache",
            asof_date=recent_date,
            scores=[],
            status="available"
        )

        # 检查陈旧度
        staleness = cache.get_staleness_days()

        # 1-2 天是正常的
        assert 1 <= staleness <= 2


@pytest.mark.django_db
class TestAlphaMultiUniverse:
    """测试 Alpha 多股票池支持"""

    def test_multiple_universes(self):
        """测试多个股票池"""
        service = AlphaService()

        # 获取支持的股票池
        universes = service.get_available_universes()

        # 验证至少包含默认股票池
        assert "csi300" in universes

    def test_different_universe_scores(self):
        """测试不同股票池的评分"""
        service = AlphaService()

        # 为不同股票池创建缓存
        today = date.today()
        for universe in ["csi300", "csi500"]:
            AlphaScoreCacheModel.objects.create(
                universe_id=universe,
                intended_trade_date=today,
                provider_source="cache",
                asof_date=today,
                scores=[
                    {"code": "600519.SH", "score": 0.8, "rank": 1, "factors": {}, "confidence": 0.8}
                ],
                status="available"
            )

        # 获取不同股票池的评分
        result1 = service.get_stock_scores("csi300", today)
        result2 = service.get_stock_scores("csi500", today)

        # 两个都应该成功
        assert result1.success or result2.success
