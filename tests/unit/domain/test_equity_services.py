"""
Tests for apps.equity.domain.services — StockScreener, ValuationAnalyzer, RegimeCorrelationAnalyzer

Pure-Python tests: no Django, pandas, or numpy imports.
Uses factory helpers from tests.factories.domain_factories.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.equity.domain.rules import StockScreeningRule
from apps.equity.domain.services import (
    RegimeCorrelationAnalyzer,
    StockScreener,
    ValuationAnalyzer,
)
from tests.factories.domain_factories import (
    make_financial_data,
    make_stock_info,
    make_valuation_metrics,
)

# ============================================================
# Helpers
# ============================================================


def _default_rule(**overrides) -> StockScreeningRule:
    """Create a permissive screening rule with optional overrides."""
    defaults = {
        "regime": "Recovery",
        "name": "测试规则",
        "min_roe": 0.0,
        "min_revenue_growth": 0.0,
        "min_profit_growth": 0.0,
        "max_debt_ratio": 100.0,
        "max_pe": 999.0,
        "max_pb": 999.0,
        "min_market_cap": Decimal(0),
        "max_count": 50,
    }
    defaults.update(overrides)
    return StockScreeningRule(**defaults)


def _make_stock_tuple(
    code: str = "000001",
    name: str = "平安银行",
    sector: str = "金融",
    roe: float = 0.12,
    revenue_growth: float = 0.08,
    net_profit_growth: float = 0.12,
    debt_ratio: float = 0.9,
    pe: float = 8.5,
    pb: float = 0.9,
    total_mv: Decimal = Decimal("300000000000"),
):
    info = make_stock_info(stock_code=code, name=name, sector=sector)
    fin = make_financial_data(
        stock_code=code,
        roe=roe,
        revenue_growth=revenue_growth,
        net_profit_growth=net_profit_growth,
        debt_ratio=debt_ratio,
    )
    val = make_valuation_metrics(stock_code=code, pe=pe, pb=pb, total_mv=total_mv)
    return (info, fin, val)


# ============================================================
# StockScreener.screen
# ============================================================


class TestStockScreener:
    """Tests for StockScreener.screen"""

    def test_screen_all_pass(self) -> None:
        """All stocks pass a permissive rule."""
        screener = StockScreener()
        stocks = [
            _make_stock_tuple("000001", roe=0.15, pe=10.0),
            _make_stock_tuple("000002", name="万科A", sector="房地产", roe=0.10, pe=12.0),
        ]
        rule = _default_rule()

        result = screener.screen(stocks, rule)

        assert len(result) == 2

    def test_screen_filters_by_roe(self) -> None:
        """Stocks below min_roe are excluded."""
        screener = StockScreener()
        stocks = [
            _make_stock_tuple("000001", roe=0.15),
            _make_stock_tuple("000002", name="低ROE", roe=0.01),
        ]
        rule = _default_rule(min_roe=0.10)

        result = screener.screen(stocks, rule)

        assert "000001" in result
        assert "000002" not in result

    def test_screen_filters_by_sector(self) -> None:
        """Stocks not in sector_preference are excluded."""
        screener = StockScreener()
        stocks = [
            _make_stock_tuple("000001", sector="金融"),
            _make_stock_tuple("000002", name="科技股", sector="科技"),
        ]
        rule = _default_rule(sector_preference=["金融"])

        result = screener.screen(stocks, rule)

        assert "000001" in result
        assert "000002" not in result

    def test_screen_max_count_limits_output(self) -> None:
        """Output is capped by max_count."""
        screener = StockScreener()
        stocks = [
            _make_stock_tuple(f"00000{i}", name=f"Stock{i}", roe=0.10 + i * 0.01)
            for i in range(5)
        ]
        rule = _default_rule(max_count=2)

        result = screener.screen(stocks, rule)

        assert len(result) <= 2

    def test_screen_empty_stocks(self) -> None:
        """Empty input returns empty list."""
        screener = StockScreener()
        result = screener.screen([], _default_rule())
        assert result == []

    def test_screen_filters_negative_pe(self) -> None:
        """Negative PE is filtered when max_pe is set."""
        screener = StockScreener()
        stocks = [_make_stock_tuple("000001", pe=-5.0)]
        rule = _default_rule(max_pe=50.0)

        result = screener.screen(stocks, rule)

        assert result == []

    def test_screen_filters_by_market_cap(self) -> None:
        """Stocks below min_market_cap are excluded."""
        screener = StockScreener()
        stocks = [
            _make_stock_tuple("000001", total_mv=Decimal("100000000000")),
            _make_stock_tuple("000002", name="小盘股", total_mv=Decimal("1000000")),
        ]
        rule = _default_rule(min_market_cap=Decimal("50000000000"))

        result = screener.screen(stocks, rule)

        assert "000001" in result
        assert "000002" not in result


# ============================================================
# ValuationAnalyzer
# ============================================================


class TestValuationAnalyzer:
    """Tests for ValuationAnalyzer"""

    @pytest.fixture
    def va(self) -> ValuationAnalyzer:
        return ValuationAnalyzer()

    # --- calculate_pe_percentile ---

    def test_pe_percentile_basic(self, va: ValuationAnalyzer) -> None:
        """PE of 15 in [5, 10, 15, 20, 25] has 2 lower => 2/5 = 0.4."""
        result = va.calculate_pe_percentile(15.0, [5.0, 10.0, 15.0, 20.0, 25.0])
        assert result == pytest.approx(0.4)

    def test_pe_percentile_lowest(self, va: ValuationAnalyzer) -> None:
        """Lowest PE yields percentile 0."""
        result = va.calculate_pe_percentile(5.0, [5.0, 10.0, 15.0, 20.0])
        assert result == pytest.approx(0.0)

    def test_pe_percentile_empty_history(self, va: ValuationAnalyzer) -> None:
        """Empty history returns 0.5."""
        assert va.calculate_pe_percentile(10.0, []) == 0.5

    def test_pe_percentile_zero_current(self, va: ValuationAnalyzer) -> None:
        """Zero current PE returns 0.5."""
        assert va.calculate_pe_percentile(0.0, [5.0, 10.0]) == 0.5

    def test_pe_percentile_negative_current(self, va: ValuationAnalyzer) -> None:
        """Negative current PE returns 0.5."""
        assert va.calculate_pe_percentile(-5.0, [5.0, 10.0]) == 0.5

    def test_pe_percentile_filters_invalid_history(
        self, va: ValuationAnalyzer
    ) -> None:
        """Negative values in history are filtered out."""
        result = va.calculate_pe_percentile(10.0, [-5.0, -10.0, 5.0, 15.0])
        # valid = [5, 15], lower than 10 => 1/2 = 0.5
        assert result == pytest.approx(0.5)

    def test_pe_percentile_all_invalid_history(self, va: ValuationAnalyzer) -> None:
        """All-negative history returns 0.5."""
        assert va.calculate_pe_percentile(10.0, [-5.0, -10.0]) == 0.5

    # --- calculate_pb_percentile ---

    def test_pb_percentile_basic(self, va: ValuationAnalyzer) -> None:
        """PB of 2.0 in [1.0, 2.0, 3.0] has 1 lower => 1/3."""
        result = va.calculate_pb_percentile(2.0, [1.0, 2.0, 3.0])
        assert result == pytest.approx(1.0 / 3.0)

    def test_pb_percentile_empty(self, va: ValuationAnalyzer) -> None:
        assert va.calculate_pb_percentile(1.0, []) == 0.5

    def test_pb_percentile_zero_current(self, va: ValuationAnalyzer) -> None:
        assert va.calculate_pb_percentile(0.0, [1.0, 2.0]) == 0.5

    # --- is_undervalued ---

    def test_is_undervalued_true(self, va: ValuationAnalyzer) -> None:
        """Both percentiles below threshold => undervalued."""
        assert va.is_undervalued(0.1, 0.1, threshold=0.3) is True

    def test_is_undervalued_false_pe_high(self, va: ValuationAnalyzer) -> None:
        """PE percentile above threshold => not undervalued."""
        assert va.is_undervalued(0.5, 0.1, threshold=0.3) is False

    def test_is_undervalued_false_pb_high(self, va: ValuationAnalyzer) -> None:
        """PB percentile above threshold => not undervalued."""
        assert va.is_undervalued(0.1, 0.5, threshold=0.3) is False

    def test_is_undervalued_edge_equal_threshold(
        self, va: ValuationAnalyzer
    ) -> None:
        """Exactly at threshold is NOT undervalued (strict less-than)."""
        assert va.is_undervalued(0.3, 0.3, threshold=0.3) is False

    # --- calculate_dcf_value ---

    def test_dcf_basic(self, va: ValuationAnalyzer) -> None:
        """DCF with default params produces a positive value."""
        result = va.calculate_dcf_value(Decimal("1000000000"))
        assert result > 0

    def test_dcf_zero_fcf(self, va: ValuationAnalyzer) -> None:
        """Zero FCF yields zero value."""
        result = va.calculate_dcf_value(Decimal("0"))
        assert result == Decimal("0")

    def test_dcf_higher_growth_higher_value(self, va: ValuationAnalyzer) -> None:
        """Higher growth rate should produce higher valuation."""
        low = va.calculate_dcf_value(Decimal("1000000000"), growth_rate=0.05)
        high = va.calculate_dcf_value(Decimal("1000000000"), growth_rate=0.15)
        assert high > low


# ============================================================
# RegimeCorrelationAnalyzer
# ============================================================


class TestRegimeCorrelationAnalyzer:
    """Tests for RegimeCorrelationAnalyzer"""

    @pytest.fixture
    def rca(self) -> RegimeCorrelationAnalyzer:
        return RegimeCorrelationAnalyzer()

    # --- calculate_regime_correlation ---

    def test_regime_correlation_basic(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Average returns are computed per regime."""
        d1, d2, d3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)
        stock_returns = {d1: 0.02, d2: 0.04, d3: -0.01}
        regime_history = {d1: "Recovery", d2: "Recovery", d3: "Overheat"}

        result = rca.calculate_regime_correlation(stock_returns, regime_history)

        assert result["Recovery"] == pytest.approx(0.03)
        assert result["Overheat"] == pytest.approx(-0.01)

    def test_regime_correlation_empty_inputs(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Empty inputs return zero for all regimes."""
        result = rca.calculate_regime_correlation({}, {})
        for regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]:
            assert result[regime] == 0.0

    def test_regime_correlation_unknown_regime_ignored(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Unknown regime names are ignored."""
        d1 = date(2024, 1, 2)
        stock_returns = {d1: 0.05}
        regime_history = {d1: "UnknownRegime"}

        result = rca.calculate_regime_correlation(stock_returns, regime_history)

        for regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]:
            assert result[regime] == 0.0

    def test_regime_correlation_no_matching_dates(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """No overlapping dates produce zero averages."""
        stock_returns = {date(2024, 1, 2): 0.05}
        regime_history = {date(2024, 1, 3): "Recovery"}

        result = rca.calculate_regime_correlation(stock_returns, regime_history)

        assert result["Recovery"] == 0.0

    # --- calculate_regime_beta ---

    def test_regime_beta_identical_returns(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Identical stock and market returns yield beta 1.0 per regime."""
        dates = [date(2024, 1, i) for i in range(2, 27)]
        returns = {d: 0.01 * (i + 1) for i, d in enumerate(dates)}
        regime = dict.fromkeys(dates, "Recovery")

        result = rca.calculate_regime_beta(returns, returns, regime)

        assert result["Recovery"] == pytest.approx(1.0, abs=1e-6)

    def test_regime_beta_empty_inputs(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Empty inputs return null beta for all regimes."""
        result = rca.calculate_regime_beta({}, {}, {})
        for regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]:
            assert result[regime] is None

    def test_regime_beta_single_data_point_default(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Single data point per regime returns null beta."""
        d1 = date(2024, 1, 2)
        stock = {d1: 0.02}
        market = {d1: 0.01}
        regime = {d1: "Overheat"}

        result = rca.calculate_regime_beta(stock, market, regime)

        assert result["Overheat"] is None

    def test_regime_beta_zero_market_variance_returns_null(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Constant market returns make beta unavailable."""
        dates = [date(2024, 1, i) for i in range(2, 27)]
        stock = {d: 0.01 * (i + 1) for i, d in enumerate(dates)}
        market = dict.fromkeys(dates, 0.05)
        regime = dict.fromkeys(dates, "Stagflation")

        result = rca.calculate_regime_beta(stock, market, regime)

        assert result["Stagflation"] is None

    def test_regime_beta_multiple_regimes(
        self, rca: RegimeCorrelationAnalyzer
    ) -> None:
        """Different regimes can produce different betas."""
        dates_r = [date(2024, 1, i) for i in range(2, 27)]
        dates_o = [date(2024, 2, i) for i in range(2, 27)]

        stock = {}
        market = {}
        regime_map = {}

        for i, d in enumerate(dates_r):
            stock[d] = 0.01 * (i + 1)
            market[d] = 0.005 * (i + 1)
            regime_map[d] = "Recovery"

        for i, d in enumerate(dates_o):
            stock[d] = -0.01 * (i + 1)
            market[d] = 0.005 * (i + 1)
            regime_map[d] = "Overheat"

        result = rca.calculate_regime_beta(stock, market, regime_map)

        # Recovery: positive covariance, Overheat: negative covariance
        assert result["Recovery"] > 0
        assert result["Overheat"] < 0
