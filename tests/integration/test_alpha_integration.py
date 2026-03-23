"""
Integration Tests for Alpha Module

测试 Alpha 模块的端到端功能。
"""

from datetime import date

import pytest

from apps.alpha.application.services import AlphaProviderRegistry, AlphaService
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.interfaces import AlphaProviderStatus
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel


@pytest.mark.django_db
class TestAlphaServiceIntegration:
    """Alpha 服务集成测试"""

    def test_service_singleton(self):
        """测试服务单例"""
        service1 = AlphaService()
        service2 = AlphaService()

        assert service1 is service2

    def test_default_providers_registered(self):
        """测试默认 Provider 已注册"""
        service = AlphaService()
        providers = service._registry.get_all_providers()

        provider_names = {p.name for p in providers}

        assert "cache" in provider_names
        assert "simple" in provider_names
        assert "etf" in provider_names

    def test_provider_priority_order(self):
        """测试 Provider 优先级顺序"""
        service = AlphaService()
        providers = service._registry.get_all_providers()

        # 验证优先级顺序
        priorities = [p.priority for p in providers]
        assert priorities == sorted(priorities)

    def test_get_stock_scores_returns_result(self):
        """测试获取股票评分返回结果"""
        service = AlphaService()
        result = service.get_stock_scores("csi300", date.today())

        assert isinstance(result, AlphaResult)
        assert isinstance(result.scores, list)

    def test_get_provider_status(self):
        """测试获取 Provider 状态"""
        service = AlphaService()
        status = service.get_provider_status()

        assert isinstance(status, dict)
        # 应该至少有 3 个 Provider
        assert len(status) >= 3

    def test_get_available_universes(self):
        """测试获取支持的股票池"""
        service = AlphaService()
        universes = service.get_available_universes()

        assert isinstance(universes, list)
        # 应该至少支持 csi300
        assert "csi300" in universes


@pytest.mark.django_db
class TestCacheProviderIntegration:
    """缓存 Provider 集成测试"""

    def test_cache_provider_properties(self):
        """测试缓存 Provider 属性"""
        provider = CacheAlphaProvider()

        assert provider.name == "cache"
        assert provider.priority == 10
        assert provider.max_staleness_days == 5

    def test_cache_provider_supports_common_universes(self):
        """测试缓存 Provider 支持常见股票池"""
        provider = CacheAlphaProvider()

        assert provider.supports("csi300")
        assert provider.supports("csi500")
        assert provider.supports("sse50")


@pytest.mark.django_db
class TestSimpleProviderIntegration:
    """简单因子 Provider 集成测试"""

    def test_simple_provider_properties(self):
        """测试简单因子 Provider 属性"""
        provider = SimpleAlphaProvider()

        assert provider.name == "simple"
        assert provider.priority == 100
        assert provider.max_staleness_days == 7


@pytest.mark.django_db
class TestETFProviderIntegration:
    """ETF 降级 Provider 集成测试"""

    def _seed_etf_data(self):
        FundInfoModel._default_manager.create(
            fund_code="510300",
            fund_name="沪深300ETF",
            fund_type="指数型",
            is_active=True,
        )
        FundInfoModel._default_manager.create(
            fund_code="510500",
            fund_name="中证500ETF",
            fund_type="指数型",
            is_active=True,
        )
        FundInfoModel._default_manager.create(
            fund_code="510050",
            fund_name="上证50ETF",
            fund_type="指数型",
            is_active=True,
        )
        for fund_code in ["510300", "510500", "510050"]:
            FundHoldingModel._default_manager.create(
                fund_code=fund_code,
                report_date=date.today(),
                stock_code="600519.SH",
                stock_name="贵州茅台",
                holding_ratio=4.5,
            )

    def test_etf_provider_properties(self):
        """测试 ETF Provider 属性"""
        provider = ETFFallbackProvider()

        assert provider.name == "etf"
        assert provider.priority == 1000
        assert provider.max_staleness_days == 30

    def test_etf_provider_universe_support(self):
        """测试 ETF Provider 股票池支持"""
        self._seed_etf_data()
        provider = ETFFallbackProvider()

        assert provider.supports("csi300")
        assert provider.supports("csi500")
        assert provider.supports("sse50")
        assert not provider.supports("unknown")

    def test_etf_provider_health_always_available(self):
        """测试 ETF Provider 健康检查总是可用"""
        provider = ETFFallbackProvider()
        health = provider.health_check()

        assert health == AlphaProviderStatus.AVAILABLE


@pytest.mark.django_db
class TestProviderFallbackIntegration:
    """Provider 降级集成测试"""

    def test_fallback_chain(self):
        """测试降级链路"""
        registry = AlphaProviderRegistry()

        # 添加测试 Provider（按优先级）
        cache_provider = CacheAlphaProvider()
        simple_provider = SimpleAlphaProvider()
        etf_provider = ETFFallbackProvider()

        registry.register(cache_provider)
        registry.register(simple_provider)
        registry.register(etf_provider)

        providers = registry.get_all_providers()

        # 验证顺序
        assert providers[0].name == "cache"
        assert providers[1].name == "simple"
        assert providers[2].name == "etf"

    def test_get_scores_with_fallback(self):
        """测试带降级的评分获取"""
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
        registry = AlphaProviderRegistry()

        # 添加 Provider
        registry.register(CacheAlphaProvider())
        registry.register(SimpleAlphaProvider())
        registry.register(ETFFallbackProvider())

        # ETF Provider 应该总是可用
        result = registry.get_scores_with_fallback("csi300", date.today())

        # 由于 ETF Provider 可用，应该返回成功
        assert result is not None
        assert result.success is True


@pytest.mark.django_db
class TestStockScoreEntity:
    """StockScore 实体测试"""

    def test_create_stock_score(self):
        """测试创建 StockScore"""
        score = StockScore(
            code="000001.SH",
            score=0.8,
            rank=1,
            factors={"momentum": 0.7, "value": 0.5},
            source="test",
            confidence=0.9,
            asof_date=date.today(),
            universe_id="csi300"
        )

        assert score.code == "000001.SH"
        assert score.score == 0.8
        assert score.rank == 1

    def test_stock_score_serialization(self):
        """测试 StockScore 序列化"""
        score = StockScore(
            code="000001.SH",
            score=0.8,
            rank=1,
            factors={},
            source="test",
            confidence=0.9
        )

        # 转字典
        data = score.to_dict()
        assert data["code"] == "000001.SH"

        # 从字典创建
        score2 = StockScore.from_dict(data)
        assert score2.code == score.code
        assert score2.score == score.score


@pytest.mark.django_db
class TestAlphaResultEntity:
    """AlphaResult 实体测试"""

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
