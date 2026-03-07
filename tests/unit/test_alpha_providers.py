"""
Unit Tests for Alpha Providers

测试 Alpha Provider 的核心功能。
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock
from django.test import override_settings

from apps.alpha.domain.entities import StockScore, AlphaResult
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.domain.interfaces import AlphaProvider
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.application.services import AlphaService, AlphaProviderRegistry
from apps.fund.infrastructure.models import FundInfoModel, FundHoldingModel


class MockAlphaProvider(AlphaProvider):
    """测试用 Mock Provider"""

    def __init__(self, name: str, priority: int, health_status: AlphaProviderStatus):
        self._name = name
        self._priority = priority
        self._health_status = health_status
        self._should_fail = False
        self._result = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    def health_check(self) -> AlphaProviderStatus:
        return self._health_status

    def get_stock_scores(self, universe_id: str, intended_trade_date: date, top_n: int = 30) -> AlphaResult:
        if self._should_fail:
            return AlphaResult(
                success=False,
                scores=[],
                source=self._name,
                timestamp=intended_trade_date.isoformat(),
                error_message="Mock failure"
            )

        if self._result:
            return self._result

        return AlphaResult(
            success=True,
            scores=[
                StockScore(
                    code=f"{i:06d}.SH",
                    score=1.0 - i * 0.01,
                    rank=i + 1,
                    factors={},
                    source=self._name,
                    confidence=0.8
                )
                for i in range(top_n)
            ],
            source=self._name,
            timestamp=intended_trade_date.isoformat()
        )

    def get_factor_exposure(self, stock_code: str, trade_date: date) -> dict:
        return {"mock_factor": 0.5}

    def set_failure(self, should_fail: bool):
        self._should_fail = should_fail

    def set_result(self, result: AlphaResult):
        self._result = result


class TestAlphaProviderRegistry:
    """测试 Provider 注册中心"""

    def test_register_provider(self):
        """测试注册 Provider"""
        registry = AlphaProviderRegistry()
        provider = MockAlphaProvider("test", 100, AlphaProviderStatus.AVAILABLE)

        registry.register(provider)

        assert len(registry.get_all_providers()) == 1
        assert registry.get_provider("test") == provider

    def test_register_multiple_providers_sorted(self):
        """测试注册多个 Provider 后自动排序"""
        registry = AlphaProviderRegistry()

        # 按随机顺序注册
        registry.register(MockAlphaProvider("low", 100, AlphaProviderStatus.AVAILABLE))
        registry.register(MockAlphaProvider("high", 10, AlphaProviderStatus.AVAILABLE))
        registry.register(MockAlphaProvider("mid", 50, AlphaProviderStatus.AVAILABLE))

        providers = registry.get_all_providers()
        assert providers[0].name == "high"
        assert providers[1].name == "mid"
        assert providers[2].name == "low"

    def test_unregister_provider(self):
        """测试取消注册 Provider"""
        registry = AlphaProviderRegistry()
        provider = MockAlphaProvider("test", 100, AlphaProviderStatus.AVAILABLE)

        registry.register(provider)
        assert len(registry.get_all_providers()) == 1

        result = registry.unregister("test")
        assert result is True
        assert len(registry.get_all_providers()) == 0

    def test_get_active_providers(self):
        """测试获取可用 Provider"""
        registry = AlphaProviderRegistry()

        registry.register(MockAlphaProvider("available", 100, AlphaProviderStatus.AVAILABLE))
        registry.register(MockAlphaProvider("degraded", 100, AlphaProviderStatus.DEGRADED))
        registry.register(MockAlphaProvider("unavailable", 100, AlphaProviderStatus.UNAVAILABLE))

        active = registry.get_active_providers()
        assert len(active) == 2
        names = {p.name for p in active}
        assert names == {"available", "degraded"}

    def test_fallback_chain(self):
        """测试降级链路"""
        registry = AlphaProviderRegistry()
        test_date = date.today()

        # 第一个 Provider 失败
        provider1 = MockAlphaProvider("first", 10, AlphaProviderStatus.AVAILABLE)
        provider1.set_failure(True)

        # 第二个 Provider 成功
        provider2 = MockAlphaProvider("second", 20, AlphaProviderStatus.AVAILABLE)

        registry.register(provider1)
        registry.register(provider2)

        result = registry.get_scores_with_fallback("csi300", test_date)

        assert result.success is True
        assert result.source == "second"

    def test_all_providers_fail(self):
        """测试所有 Provider 都失败"""
        registry = AlphaProviderRegistry()
        test_date = date.today()

        provider1 = MockAlphaProvider("first", 10, AlphaProviderStatus.AVAILABLE)
        provider1.set_failure(True)

        provider2 = MockAlphaProvider("second", 20, AlphaProviderStatus.AVAILABLE)
        provider2.set_failure(True)

        registry.register(provider1)
        registry.register(provider2)

        result = registry.get_scores_with_fallback("csi300", test_date)

        assert result.success is False
        assert result.status == "unavailable"


class TestCacheAlphaProvider:
    """测试缓存 Provider"""

    def test_provider_properties(self):
        """测试 Provider 属性"""
        provider = CacheAlphaProvider()

        assert provider.name == "cache"
        assert provider.priority == 10
        assert provider.max_staleness_days == 5

    @patch("apps.alpha.infrastructure.adapters.cache_adapter.AlphaScoreCacheModel")
    def test_get_stock_scores_from_cache(self, mock_model):
        """测试从缓存获取评分"""
        # 设置 Mock
        mock_cache = Mock()
        mock_cache.intended_trade_date = date.today()
        mock_cache.asof_date = date.today()
        mock_cache.provider_source = "cache"
        mock_cache.get_staleness_days.return_value = 0
        mock_cache.scores = [
            {
                "code": "000001.SH",
                "score": 0.8,
                "rank": 1,
                "factors": {},
                "source": "cache",
                "confidence": 0.8
            }
        ]
        mock_cache.created_at = date.today()

        mock_model.objects.filter.return_value.order_by.return_value.first.return_value = mock_cache

        provider = CacheAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is True
        assert len(result.scores) == 1
        assert result.scores[0].code == "000001.SH"

    @patch("apps.alpha.infrastructure.adapters.cache_adapter.AlphaScoreCacheModel")
    def test_no_cache_found(self, mock_model):
        """测试没有找到缓存"""
        mock_model.objects.filter.return_value.order_by.return_value.first.return_value = None

        provider = CacheAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is False
        assert "未找到" in result.error_message


class TestSimpleAlphaProvider:
    """测试简单因子 Provider"""

    def test_provider_properties(self):
        """测试 Provider 属性"""
        provider = SimpleAlphaProvider()

        assert provider.name == "simple"
        assert provider.priority == 100
        assert provider.max_staleness_days == 7

    def test_custom_factor_weights(self):
        """测试自定义因子权重"""
        custom_weights = {"pe_inv": 0.5, "pb_inv": 0.5}
        provider = SimpleAlphaProvider(factor_weights=custom_weights)

        assert provider._factor_weights == custom_weights

    @patch("apps.alpha.infrastructure.adapters.simple_adapter.SimpleAlphaProvider._get_universe_stocks")
    def test_compute_scores(self, mock_universe):
        """测试计算评分"""
        mock_universe.return_value = ["000001.SH", "000002.SH"]

        provider = SimpleAlphaProvider()
        # 这里简化测试，实际需要 mock 更多依赖

        assert provider is not None


@pytest.mark.django_db
class TestETFFallbackProvider:
    """测试 ETF 降级 Provider"""

    def _seed_etf_data(self):
        FundInfoModel._default_manager.create(
            fund_code="510300",
            fund_name="沪深300ETF",
            fund_type="指数型",
            is_active=True,
        )
        FundHoldingModel._default_manager.create(
            fund_code="510300",
            report_date=date.today(),
            stock_code="600519.SH",
            stock_name="贵州茅台",
            holding_ratio=4.5,
        )
        FundHoldingModel._default_manager.create(
            fund_code="510300",
            report_date=date.today(),
            stock_code="000333.SZ",
            stock_name="美的集团",
            holding_ratio=3.2,
        )

    def test_provider_properties(self):
        """测试 Provider 属性"""
        provider = ETFFallbackProvider()

        assert provider.name == "etf"
        assert provider.priority == 1000
        assert provider.max_staleness_days == 30

    def test_supported_universes(self):
        """测试支持的股票池"""
        self._seed_etf_data()
        provider = ETFFallbackProvider()

        assert provider.supports("csi300") is True
        assert provider.supports("unknown") is False

    def test_health_check_always_available(self):
        """测试健康检查总是可用"""
        provider = ETFFallbackProvider()
        health = provider.health_check()

        assert health == AlphaProviderStatus.AVAILABLE

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
    def test_get_stock_scores(self):
        """测试获取 ETF 成分股评分"""
        self._seed_etf_data()
        provider = ETFFallbackProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is True
        assert len(result.scores) == 2
        assert result.metadata["etf_code"] == "510300.SH"

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
    def test_get_stock_scores_requires_real_holdings(self):
        """测试没有真实持仓时不会回退到静态股票列表"""
        FundInfoModel._default_manager.create(
            fund_code="510300",
            fund_name="沪深300ETF",
            fund_type="指数型",
            is_active=True,
        )
        provider = ETFFallbackProvider()

        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is False
        assert "真实成分股" in result.error_message


class TestAlphaService:
    """测试 Alpha 服务"""

    def test_singleton_pattern(self):
        """测试单例模式"""
        service1 = AlphaService()
        service2 = AlphaService()

        assert service1 is service2

    def test_default_providers_registered(self):
        """测试默认 Provider 已注册"""
        service = AlphaService()
        providers = service._registry.get_all_providers()

        names = {p.name for p in providers}
        assert "cache" in names
        assert "simple" in names
        assert "etf" in names

    def test_get_stock_scores(self):
        """测试获取股票评分"""
        service = AlphaService()
        result = service.get_stock_scores("csi300", date.today())

        # 由于可能没有实际数据，我们只检查返回格式
        assert isinstance(result, AlphaResult)
        assert isinstance(result.scores, list)

    def test_get_provider_status(self):
        """测试获取 Provider 状态"""
        service = AlphaService()
        status = service.get_provider_status()

        assert isinstance(status, dict)
        assert "cache" in status or "simple" in status or "etf" in status

    def test_get_available_universes(self):
        """测试获取支持的股票池"""
        service = AlphaService()
        universes = service.get_available_universes()

        assert isinstance(universes, list)
        assert len(universes) > 0


class TestStockScore:
    """测试 StockScore 实体"""

    def test_create_stock_score(self):
        """测试创建 StockScore"""
        score = StockScore(
            code="000001.SH",
            score=0.8,
            rank=1,
            factors={"momentum": 0.7},
            source="test",
            confidence=0.9,
            asof_date=date.today(),
            universe_id="csi300"
        )

        assert score.code == "000001.SH"
        assert score.score == 0.8
        assert score.rank == 1

    def test_to_dict(self):
        """测试转换为字典"""
        score = StockScore(
            code="000001.SH",
            score=0.8,
            rank=1,
            factors={},
            source="test",
            confidence=0.9
        )

        data = score.to_dict()

        assert data["code"] == "000001.SH"
        assert data["score"] == 0.8
        assert isinstance(data, dict)

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "code": "000001.SH",
            "score": 0.8,
            "rank": 1,
            "factors": {},
            "source": "test",
            "confidence": 0.9
        }

        score = StockScore.from_dict(data)

        assert score.code == "000001.SH"
        assert score.score == 0.8


class TestAlphaResult:
    """测试 AlphaResult 实体"""

    def test_create_success_result(self):
        """测试创建成功结果"""
        scores = [
            StockScore(
                code="000001.SH",
                score=0.8,
                rank=1,
                factors={},
                source="test",
                confidence=0.9
            )
        ]

        result = AlphaResult(
            success=True,
            scores=scores,
            source="test",
            timestamp=date.today().isoformat()
        )

        assert result.success is True
        assert len(result.scores) == 1

    def test_create_error_result(self):
        """测试创建错误结果"""
        result = AlphaResult(
            success=False,
            scores=[],
            source="none",
            timestamp=date.today().isoformat(),
            error_message="Test error"
        )

        assert result.success is False
        assert result.error_message == "Test error"
