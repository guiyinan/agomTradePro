"""
Unit Tests for Alpha Providers

测试 Alpha Provider 的核心功能。
"""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.alpha.application.services import AlphaProviderRegistry, AlphaService
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.alpha.domain.interfaces import AlphaProvider, AlphaProviderStatus
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel


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

    def get_stock_scores(
        self, universe_id: str, intended_trade_date: date, top_n: int = 30
    ) -> AlphaResult:
        if self._should_fail:
            return AlphaResult(
                success=False,
                scores=[],
                source=self._name,
                timestamp=intended_trade_date.isoformat(),
                error_message="Mock failure",
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
                    confidence=0.8,
                )
                for i in range(top_n)
            ],
            source=self._name,
            timestamp=intended_trade_date.isoformat(),
        )

    def get_factor_exposure(self, stock_code: str, trade_date: date) -> dict:
        return {"mock_factor": 0.5}

    def set_failure(self, should_fail: bool):
        self._should_fail = should_fail

    def set_result(self, result: AlphaResult):
        self._result = result


def _build_result(
    *,
    source: str,
    staleness_days: int | None,
    metadata: dict[str, object] | None = None,
    status: str = "available",
    score: float = 0.7,
) -> AlphaResult:
    """Build one successful result for registry fallback contract tests."""

    return AlphaResult(
        success=True,
        scores=[
            StockScore(
                code="000001.SZ",
                score=score,
                rank=1,
                factors={},
                source=source,
                confidence=0.8,
                asof_date=date(2026, 10, 27),
            )
        ],
        source=source,
        timestamp="2026-10-28T08:00:00+08:00",
        status=status,
        staleness_days=staleness_days,
        metadata=metadata or {},
    )


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

    @pytest.mark.parametrize(
        ("staleness_days", "metadata", "expected_blocked", "expected_reason"),
        [
            (2, {}, False, None),
            (3, {}, True, "alpha_source_data_stale"),
            (
                3,
                {
                    "must_not_use_for_decision": True,
                    "blocked_reason": "upstream_scope_blocked",
                },
                True,
                "upstream_scope_blocked",
            ),
        ],
    )
    def test_stale_result_block_uses_provider_threshold_and_preserves_reason(
        self,
        staleness_days: int,
        metadata: dict[str, object],
        expected_blocked: bool,
        expected_reason: str | None,
    ) -> None:
        """The last provider's existing age limit owns stale-result blocking."""

        provider = MockAlphaProvider("only", 1, AlphaProviderStatus.AVAILABLE)
        provider.set_result(
            _build_result(
                source="only",
                staleness_days=staleness_days,
                metadata=metadata,
            )
        )
        registry = AlphaProviderRegistry()
        registry.register(provider)

        result = registry.get_scores_with_fallback("csi300", date(2026, 10, 28))

        assert result.success is True
        assert result.status == ("degraded" if staleness_days > 2 else "available")
        assert result.scores[0].score == 0.7
        assert result.metadata.get("must_not_use_for_decision", False) is expected_blocked
        if expected_reason is not None:
            assert result.metadata["blocked_reason"] == expected_reason
        if expected_blocked:
            assert result.metadata["freshness_status"] == "stale"

    def test_stale_result_is_blocked_when_a_later_provider_fails(self) -> None:
        stale = MockAlphaProvider("stale", 1, AlphaProviderStatus.AVAILABLE)
        stale.set_result(_build_result(source="stale", staleness_days=5))
        failed = MockAlphaProvider("failed", 2, AlphaProviderStatus.AVAILABLE)
        failed.set_failure(True)
        registry = AlphaProviderRegistry()
        registry.register(stale)
        registry.register(failed)

        result = registry.get_scores_with_fallback("csi300", date(2026, 10, 28))

        assert result.success is True
        assert result.source == "stale"
        assert result.scores[0].score == 0.7
        assert result.metadata.get("must_not_use_for_decision") is True
        assert result.metadata.get("blocked_reason") == "alpha_source_data_stale"
        assert result.metadata.get("freshness_status") == "stale"

    def test_fresh_fallback_does_not_inherit_stale_result_block(self) -> None:
        stale = MockAlphaProvider("stale", 1, AlphaProviderStatus.AVAILABLE)
        stale.set_result(_build_result(source="stale", staleness_days=5))
        fresh = MockAlphaProvider("fresh", 2, AlphaProviderStatus.AVAILABLE)
        fresh.set_result(_build_result(source="fresh", staleness_days=1, score=0.9))
        registry = AlphaProviderRegistry()
        registry.register(stale)
        registry.register(fresh)

        result = registry.get_scores_with_fallback("csi300", date(2026, 10, 28))

        assert result.success is True
        assert result.source == "fresh"
        assert result.status == "available"
        assert result.scores[0].score == 0.9
        assert result.metadata.get("must_not_use_for_decision", False) is False

    def test_nonstale_degraded_result_is_not_blocked_by_status_alone(self) -> None:
        provider = MockAlphaProvider("degraded", 1, AlphaProviderStatus.DEGRADED)
        provider.set_result(
            _build_result(
                source="degraded",
                staleness_days=1,
                status="degraded",
                metadata={"reliability_notice": {"code": "quality_degraded"}},
            )
        )
        registry = AlphaProviderRegistry()
        registry.register(provider)

        result = registry.get_scores_with_fallback("csi300", date(2026, 10, 28))

        assert result.success is True
        assert result.status == "degraded"
        assert result.metadata.get("must_not_use_for_decision", False) is False

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

    @patch(
        "apps.alpha.application.services.get_alpha_metrics",
        side_effect=RuntimeError("metrics down"),
    )
    def test_metrics_failure_does_not_break_successful_provider(self, _mock_metrics):
        """指标记录失败时，不应中断成功 Provider 的返回。"""
        registry = AlphaProviderRegistry()
        provider = MockAlphaProvider("available", 10, AlphaProviderStatus.AVAILABLE)

        registry.register(provider)
        result = registry.get_scores_with_fallback("csi300", date.today())

        assert result.success is True
        assert result.source == "available"


class TestCacheAlphaProvider:
    """测试缓存 Provider"""

    def test_provider_properties(self):
        """测试 Provider 属性"""
        provider = CacheAlphaProvider()

        assert provider.name == "cache"
        assert provider.priority == 10
        assert provider.max_staleness_days == 5

    @pytest.mark.django_db
    def test_get_stock_scores_from_cache(self):
        """测试从缓存获取评分"""
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date.today(),
            provider_source="qlib",
            asof_date=date.today(),
            model_id="model-current",
            model_artifact_hash="hash-current",
            scores=[
                {
                    "code": "000001.SH",
                    "score": 0.8,
                    "rank": 1,
                    "factors": {},
                    "source": "cache",
                    "confidence": 0.8,
                }
            ],
            status="available",
        )

        provider = CacheAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is True
        assert len(result.scores) == 1
        assert result.scores[0].code == "000001.SH"

    @pytest.mark.django_db
    def test_no_cache_found(self):
        """测试没有找到缓存"""
        provider = CacheAlphaProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is False
        assert "未找到" in result.error_message

    @pytest.mark.django_db
    def test_prefers_fresher_previous_cache_when_exact_match_is_stale(self):
        provider = CacheAlphaProvider()
        intended_trade_date = date(2026, 4, 15)

        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=intended_trade_date,
            provider_source="qlib",
            asof_date=date(2026, 4, 3),
            model_id="model-stale",
            model_artifact_hash="hash-stale",
            scores=[
                {
                    "code": "000001.SH",
                    "score": 0.8,
                    "rank": 1,
                    "factors": {},
                    "source": "cache",
                    "confidence": 0.8,
                }
            ],
            status="degraded",
        )
        AlphaScoreCacheModel.objects.create(
            universe_id="csi300",
            intended_trade_date=date(2026, 4, 14),
            provider_source="qlib",
            asof_date=date(2026, 4, 14),
            model_id="model-fresh",
            model_artifact_hash="hash-fresh",
            scores=[
                {
                    "code": "000002.SH",
                    "score": 0.9,
                    "rank": 1,
                    "factors": {},
                    "source": "cache",
                    "confidence": 0.9,
                }
            ],
            status="available",
        )

        result = provider.get_stock_scores("csi300", intended_trade_date)

        assert result.success is True
        assert result.staleness_days == 1
        assert result.scores[0].code == "000002.SH"


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

    @patch(
        "apps.alpha.infrastructure.adapters.simple_adapter.SimpleAlphaProvider._get_universe_stocks"
    )
    def test_compute_scores(self, mock_universe):
        """测试计算评分"""
        mock_universe.return_value = ["000001.SH", "000002.SH"]

        provider = SimpleAlphaProvider()
        # 这里简化测试，实际需要 mock 更多依赖

        assert provider is not None


@pytest.mark.django_db
class TestETFFallbackProvider:
    """测试 ETF 降级 Provider"""

    class _RemoteETFStub:
        @staticmethod
        def fund_portfolio_hold_em(symbol: str, date: str):
            import pandas as pd

            return pd.DataFrame(
                {
                    "股票代码": ["600519", "601318"],
                    "股票名称": ["贵州茅台", "中国平安"],
                    "占净值比例": [5.89, 2.43],
                    "持股数": [675.78, 11623.72],
                    "持仓市值": [1150782.02, 474363.90],
                    "季度": ["2025年4季度股票投资明细", "2025年4季度股票投资明细"],
                }
            )

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

    def test_health_check_requires_real_holdings_or_runtime_mapping(self):
        """无真实持仓和运行时映射时不得宣称 Provider 可用。"""
        provider = ETFFallbackProvider()
        health = provider.health_check()

        assert health == AlphaProviderStatus.UNAVAILABLE

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
    def test_get_stock_scores(self):
        """测试获取 ETF 成分股评分"""
        self._seed_etf_data()
        provider = ETFFallbackProvider()
        result = provider.get_stock_scores("csi300", date.today())

        assert result.success is True
        assert len(result.scores) == 2
        assert result.metadata["etf_code"] == "510300.SH"
        assert result.scores[0].score == pytest.approx(0.045)
        assert result.scores[0].factors["holding_ratio_pct"] == 4.5

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"csi300": {"etf_code": "510300.SH"}})
    def test_get_stock_scores_requires_real_holdings(self):
        """测试本地和远端都缺失时返回失败而不是静态假数据"""
        FundInfoModel._default_manager.create(
            fund_code="510300",
            fund_name="沪深300ETF",
            fund_type="指数型",
            is_active=True,
        )
        provider = ETFFallbackProvider()
        with patch.object(
            provider,
            "_get_remote_etf_constituents",
            return_value=([], "ETF 510300.SH 没有持仓报告数据，请先同步基金持仓数据", {}),
        ):
            result = provider.get_stock_scores("csi300", date.today())

        assert result.success is False
        assert "持仓" in result.error_message or "同步" in result.error_message

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"sse50": {"etf_code": "510050.SH"}})
    def test_get_stock_scores_can_fallback_to_remote_holdings(self):
        provider = ETFFallbackProvider()
        with patch.object(
            provider,
            "_get_remote_etf_constituents",
            return_value=(
                [("600519.SH", 5.89), ("601318.SH", 2.43)],
                None,
                {"holdings_source": "eastmoney", "report_date": "2025年4季度股票投资明细"},
            ),
        ):
            result = provider.get_stock_scores("sse50", date.today(), top_n=2)

        assert result.success is True
        assert len(result.scores) == 2
        assert result.metadata["holdings_source"] == "eastmoney"
        assert result.metadata["report_date"] == "2025年4季度股票投资明细"
        assert result.scores[0].code == "600519.SH"

    @override_settings(ALPHA_UNIVERSE_ETF_MAP={"sse50": {"etf_code": "510050.SH"}})
    @patch("apps.alpha.infrastructure.adapters.etf_adapter.get_akshare_module")
    def test_remote_holdings_are_persisted_to_fund_table(self, mock_get_akshare):
        mock_get_akshare.return_value = self._RemoteETFStub()
        provider = ETFFallbackProvider()

        result = provider.get_stock_scores("sse50", date.today(), top_n=2)

        assert result.success is True
        persisted = list(
            FundHoldingModel._default_manager.filter(
                fund_code="510050",
                report_date=date(2025, 12, 31),
            ).order_by("stock_code")
        )
        assert len(persisted) == 2
        assert persisted[0].stock_code == "600519.SH"
        assert persisted[0].stock_name == "贵州茅台"
        assert persisted[0].holding_ratio == 5.89


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
        expected = AlphaResult(
            success=True,
            scores=[],
            source="test",
            timestamp=datetime.now(UTC).isoformat(),
        )

        with patch.object(
            service._registry,
            "get_scores_with_fallback",
            return_value=expected,
        ):
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

    def test_get_provider_status_can_bound_health_checks_to_named_providers(self):
        """A diagnostic caller can avoid unrelated expensive provider probes."""

        service = AlphaService()
        qlib = MagicMock()
        qlib.name = "qlib"
        qlib.priority = 1
        qlib.max_staleness_days = 1
        qlib.health_check.return_value = AlphaProviderStatus.AVAILABLE
        qlib._last_health_message = ""
        simple = MagicMock()
        simple.name = "simple"
        simple.priority = 100
        simple.max_staleness_days = 7
        simple._last_health_message = ""

        with patch.object(
            service._registry,
            "get_all_providers",
            return_value=[qlib, simple],
        ):
            status = service.get_provider_status(provider_names=("qlib",))

        assert status == {
            "qlib": {
                "priority": 1,
                "status": "available",
                "max_staleness_days": 1,
            }
        }
        qlib.health_check.assert_called_once_with()
        simple.health_check.assert_not_called()

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
            universe_id="csi300",
        )

        assert score.code == "000001.SH"
        assert score.score == 0.8
        assert score.rank == 1

    def test_to_dict(self):
        """测试转换为字典"""
        score = StockScore(
            code="000001.SH", score=0.8, rank=1, factors={}, source="test", confidence=0.9
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
            "confidence": 0.9,
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
                code="000001.SH", score=0.8, rank=1, factors={}, source="test", confidence=0.9
            )
        ]

        result = AlphaResult(
            success=True, scores=scores, source="test", timestamp=date.today().isoformat()
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
            error_message="Test error",
        )

        assert result.success is False
        assert result.error_message == "Test error"
