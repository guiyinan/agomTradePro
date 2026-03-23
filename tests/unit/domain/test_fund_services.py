"""
Fund Domain Services - Comprehensive Unit Tests

Tests for FundScreener, FundStyleAnalyzer, and FundPerformanceCalculator.
Pure domain tests: no Django, pandas, or numpy dependencies.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.fund.domain.services import (
    FundPerformanceCalculator,
    FundScreener,
    FundStyleAnalyzer,
)
from tests.factories.domain_factories import (
    make_fund_holding,
    make_fund_info,
    make_fund_net_value,
    make_fund_performance,
    make_fund_sector_allocation,
)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def screener() -> FundScreener:
    return FundScreener()


@pytest.fixture
def style_analyzer() -> FundStyleAnalyzer:
    return FundStyleAnalyzer()


@pytest.fixture
def perf_calculator() -> FundPerformanceCalculator:
    return FundPerformanceCalculator()


def _build_fund_tuple(
    fund_code: str = "110011",
    fund_name: str = "测试基金A",
    fund_type: str = "混合型",
    investment_style: str = "成长",
    fund_scale: Decimal = Decimal("5000000000"),
    total_return: float = 15.0,
    annualized_return: float = 12.0,
    sharpe_ratio: float = 1.5,
    max_drawdown: float = 10.0,
    sectors: list | None = None,
):
    """Helper to build a (FundInfo, FundPerformance, List[FundSectorAllocation]) tuple."""
    info = make_fund_info(
        fund_code=fund_code,
        fund_name=fund_name,
        fund_type=fund_type,
        investment_style=investment_style,
        fund_scale=fund_scale,
    )
    perf = make_fund_performance(
        fund_code=fund_code,
        total_return=total_return,
        annualized_return=annualized_return,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
    )
    sector_allocs = sectors or []
    return (info, perf, sector_allocs)


# ============================================================
# FundScreener Tests
# ============================================================


class TestFundScreenerScreenByRegime:
    """Tests for FundScreener.screen_by_regime"""

    def test_basic_type_match(self, screener: FundScreener) -> None:
        """Funds matching preferred type are returned."""
        fund = _build_fund_tuple(fund_code="F001", fund_type="混合型")
        result = screener.screen_by_regime(
            [fund],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result == ["F001"]

    def test_type_mismatch_filtered_out(self, screener: FundScreener) -> None:
        """Funds not matching preferred type are excluded."""
        fund = _build_fund_tuple(fund_code="F001", fund_type="债券型")
        result = screener.screen_by_regime(
            [fund],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result == []

    def test_style_mismatch_filtered_out(self, screener: FundScreener) -> None:
        """Funds not matching preferred style are excluded."""
        fund = _build_fund_tuple(fund_code="F001", fund_type="混合型", investment_style="价值")
        result = screener.screen_by_regime(
            [fund],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result == []

    def test_none_style_passes_filter(self, screener: FundScreener) -> None:
        """Funds with None investment_style pass the style filter."""
        info = make_fund_info(fund_code="F001", fund_type="混合型")
        # investment_style defaults to None
        perf = make_fund_performance(fund_code="F001", total_return=10.0)
        result = screener.screen_by_regime(
            [(info, perf, [])],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result == ["F001"]

    def test_min_scale_filter(self, screener: FundScreener) -> None:
        """Funds below min_scale are excluded."""
        fund = _build_fund_tuple(
            fund_code="F001",
            fund_type="混合型",
            fund_scale=Decimal("100000000"),  # 1 yi
        )
        result = screener.screen_by_regime(
            [fund],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
            min_scale=Decimal("500000000"),  # 5 yi
        )
        assert result == []

    def test_max_count_limits_results(self, screener: FundScreener) -> None:
        """Results are limited to max_count."""
        funds = [
            _build_fund_tuple(
                fund_code=f"F{i:03d}",
                fund_type="混合型",
                total_return=float(i),
                annualized_return=float(i),
                sharpe_ratio=float(i) / 10,
            )
            for i in range(10)
        ]
        result = screener.screen_by_regime(
            funds,
            preferred_types=["混合型"],
            preferred_styles=["成长"],
            max_count=3,
        )
        assert len(result) == 3

    def test_sorted_by_score_descending(self, screener: FundScreener) -> None:
        """Results are sorted by score in descending order."""
        low = _build_fund_tuple(
            fund_code="LOW", fund_type="混合型",
            total_return=5.0, annualized_return=5.0, sharpe_ratio=0.5,
        )
        high = _build_fund_tuple(
            fund_code="HIGH", fund_type="混合型",
            total_return=30.0, annualized_return=30.0, sharpe_ratio=2.5,
        )
        result = screener.screen_by_regime(
            [low, high],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result[0] == "HIGH"
        assert result[1] == "LOW"

    def test_empty_fund_list(self, screener: FundScreener) -> None:
        """Empty input returns empty list."""
        result = screener.screen_by_regime(
            [],
            preferred_types=["混合型"],
            preferred_styles=["成长"],
        )
        assert result == []

    def test_multiple_preferred_types(self, screener: FundScreener) -> None:
        """Multiple preferred types match correctly."""
        f1 = _build_fund_tuple(fund_code="F001", fund_type="混合型")
        f2 = _build_fund_tuple(fund_code="F002", fund_type="股票型")
        f3 = _build_fund_tuple(fund_code="F003", fund_type="债券型")
        result = screener.screen_by_regime(
            [f1, f2, f3],
            preferred_types=["混合型", "股票型"],
            preferred_styles=["成长"],
        )
        assert "F001" in result
        assert "F002" in result
        assert "F003" not in result


class TestFundScreenerRankFunds:
    """Tests for FundScreener.rank_funds"""

    def test_single_fund_rank_is_one(self, screener: FundScreener) -> None:
        """A single fund gets rank 1."""
        fund = _build_fund_tuple(fund_code="F001")
        result = screener.rank_funds(
            [fund],
            regime_weights={"混合型_成长": 0.8},
        )
        assert len(result) == 1
        assert result[0].rank == 1
        assert result[0].fund_code == "F001"

    def test_ranks_are_sequential(self, screener: FundScreener) -> None:
        """Multiple funds get sequential ranks starting at 1."""
        funds = [
            _build_fund_tuple(fund_code=f"F{i:03d}", total_return=float(i) * 5)
            for i in range(5)
        ]
        result = screener.rank_funds(funds, regime_weights={})
        ranks = [s.rank for s in result]
        assert ranks == [1, 2, 3, 4, 5]

    def test_higher_return_ranked_first(self, screener: FundScreener) -> None:
        """Fund with higher total return is ranked higher."""
        low = _build_fund_tuple(fund_code="LOW", total_return=5.0, annualized_return=5.0)
        high = _build_fund_tuple(fund_code="HIGH", total_return=40.0, annualized_return=40.0)
        result = screener.rank_funds(
            [low, high],
            regime_weights={},
        )
        assert result[0].fund_code == "HIGH"
        assert result[0].rank == 1

    def test_empty_fund_list(self, screener: FundScreener) -> None:
        """Empty list returns empty result."""
        result = screener.rank_funds([], regime_weights={})
        assert result == []

    def test_regime_weights_affect_score(self, screener: FundScreener) -> None:
        """Regime weights influence the regime_fit_score."""
        fund = _build_fund_tuple(fund_code="F001")
        # High weight for this style
        result_high = screener.rank_funds(
            [fund],
            regime_weights={"混合型_成长": 0.9},
        )
        # Low weight (default 0.5)
        result_low = screener.rank_funds(
            [fund],
            regime_weights={},
        )
        assert result_high[0].regime_fit_score > result_low[0].regime_fit_score

    def test_fund_score_fields_populated(self, screener: FundScreener) -> None:
        """All FundScore fields are populated."""
        fund = _build_fund_tuple(fund_code="F001", fund_name="测试基金")
        result = screener.rank_funds([fund], regime_weights={})
        score = result[0]
        assert score.fund_code == "F001"
        assert score.fund_name == "测试基金"
        assert score.score_date is not None
        assert isinstance(score.performance_score, float)
        assert isinstance(score.regime_fit_score, float)
        assert isinstance(score.risk_score, float)
        assert isinstance(score.scale_score, float)
        assert isinstance(score.total_score, float)

    def test_scale_score_ideal_range(self, screener: FundScreener) -> None:
        """Fund with ideal scale (10-100 yi) gets 90 scale score."""
        # 50 yi = 5_000_000_000 yuan
        fund = _build_fund_tuple(
            fund_code="F001",
            fund_scale=Decimal("5000000000"),
        )
        result = screener.rank_funds([fund], regime_weights={})
        assert result[0].scale_score == 90.0

    def test_scale_score_too_small(self, screener: FundScreener) -> None:
        """Very small fund gets low scale score."""
        # 0.5 yi = 50_000_000 yuan
        fund = _build_fund_tuple(
            fund_code="F001",
            fund_scale=Decimal("50000000"),
        )
        result = screener.rank_funds([fund], regime_weights={})
        assert result[0].scale_score == 30.0

    def test_scale_score_too_large(self, screener: FundScreener) -> None:
        """Very large fund gets lower scale score."""
        # 600 yi = 60_000_000_000 yuan
        fund = _build_fund_tuple(
            fund_code="F001",
            fund_scale=Decimal("60000000000"),
        )
        result = screener.rank_funds([fund], regime_weights={})
        assert result[0].scale_score == 50.0


# ============================================================
# FundStyleAnalyzer Tests
# ============================================================


class TestFundStyleAnalyzerHoldingStyle:
    """Tests for FundStyleAnalyzer.analyze_holding_style"""

    def test_growth_sector_stocks(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Stocks from growth sectors are classified as growth style."""
        holdings = [
            make_fund_holding(stock_name="电子科技A", holding_ratio=50.0),
            make_fund_holding(stock_name="计算机软件B", holding_ratio=50.0),
        ]
        result = style_analyzer.analyze_holding_style(holdings)
        assert result["成长"] > 0
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_value_sector_stocks(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Stocks from value sectors are classified as value style."""
        holdings = [
            make_fund_holding(stock_name="银行A", holding_ratio=60.0),
            make_fund_holding(stock_name="房地产B", holding_ratio=40.0),
        ]
        result = style_analyzer.analyze_holding_style(holdings)
        assert result["价值"] > 0

    def test_balanced_unrecognized_sector(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Stocks without matching sector names are classified as balanced."""
        holdings = [
            make_fund_holding(stock_name="消费品A", holding_ratio=100.0),
        ]
        result = style_analyzer.analyze_holding_style(holdings)
        assert result["平衡"] > 0

    def test_empty_holdings(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Empty holdings returns zero weights (with normalization fallback)."""
        result = style_analyzer.analyze_holding_style([])
        # All zero, but total is 0 so fallback to 0 each
        assert result == {"成长": 0.0, "价值": 0.0, "平衡": 0.0}

    def test_none_holding_ratio_skipped(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Holdings with None holding_ratio are skipped."""
        holdings = [
            make_fund_holding(stock_name="银行A", holding_ratio=None),
            make_fund_holding(stock_name="电子B", holding_ratio=80.0),
        ]
        result = style_analyzer.analyze_holding_style(holdings)
        # Only 电子B (growth) counts
        assert result["成长"] > 0.9

    def test_weights_sum_to_one(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Style weights always sum to 1.0 when there are valid holdings."""
        holdings = [
            make_fund_holding(stock_name="银行A", holding_ratio=30.0),
            make_fund_holding(stock_name="电子B", holding_ratio=40.0),
            make_fund_holding(stock_name="消费C", holding_ratio=30.0),
        ]
        result = style_analyzer.analyze_holding_style(holdings)
        assert abs(sum(result.values()) - 1.0) < 1e-9


class TestFundStyleAnalyzerSectorConcentration:
    """Tests for FundStyleAnalyzer.analyze_sector_concentration"""

    def test_empty_sector_alloc(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Empty allocation returns zero index and concentration."""
        result = style_analyzer.analyze_sector_concentration([])
        assert result["herfindahl_index"] == 0.0
        assert result["top3_concentration"] == 0.0

    def test_single_sector_max_concentration(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Single sector allocation gives maximum concentration."""
        allocs = [make_fund_sector_allocation(sector_name="金融", allocation_ratio=100.0)]
        result = style_analyzer.analyze_sector_concentration(allocs)
        assert result["herfindahl_index"] == pytest.approx(1.0)
        assert result["top3_concentration"] == pytest.approx(100.0)

    def test_two_equal_sectors(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Two equal sectors give HHI of 0.5."""
        allocs = [
            make_fund_sector_allocation(sector_name="金融", allocation_ratio=50.0),
            make_fund_sector_allocation(sector_name="科技", allocation_ratio=50.0),
        ]
        result = style_analyzer.analyze_sector_concentration(allocs)
        expected_hhi = 2 * (0.5 ** 2)  # 0.5
        assert result["herfindahl_index"] == pytest.approx(expected_hhi)
        assert result["top3_concentration"] == pytest.approx(100.0)

    def test_top3_with_many_sectors(self, style_analyzer: FundStyleAnalyzer) -> None:
        """Top 3 concentration is computed from the largest 3 sectors."""
        allocs = [
            make_fund_sector_allocation(sector_name="A", allocation_ratio=30.0),
            make_fund_sector_allocation(sector_name="B", allocation_ratio=25.0),
            make_fund_sector_allocation(sector_name="C", allocation_ratio=20.0),
            make_fund_sector_allocation(sector_name="D", allocation_ratio=15.0),
            make_fund_sector_allocation(sector_name="E", allocation_ratio=10.0),
        ]
        result = style_analyzer.analyze_sector_concentration(allocs)
        assert result["top3_concentration"] == pytest.approx(75.0)


# ============================================================
# FundPerformanceCalculator Tests
# ============================================================


class TestCalculateTotalReturn:
    """Tests for FundPerformanceCalculator.calculate_total_return"""

    def test_positive_return(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Positive total return calculation."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 12, 31), unit_nav=Decimal("1.2000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == pytest.approx(20.0)

    def test_negative_return(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Negative total return calculation."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 12, 31), unit_nav=Decimal("0.8000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == pytest.approx(-20.0)

    def test_zero_start_nav(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Zero start NAV returns 0 to avoid division by zero."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("0")),
            make_fund_net_value(nav_date=date(2024, 12, 31), unit_nav=Decimal("1.0000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == 0.0

    def test_negative_start_nav(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Negative start NAV returns 0."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("-1.0000")),
            make_fund_net_value(nav_date=date(2024, 12, 31), unit_nav=Decimal("1.0000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == 0.0

    def test_single_nav_entry(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Single NAV entry returns 0."""
        navs = [make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.5000"))]
        result = perf_calculator.calculate_total_return(navs)
        assert result == 0.0

    def test_empty_nav_series(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Empty NAV series returns 0."""
        result = perf_calculator.calculate_total_return([])
        assert result == 0.0

    def test_no_change(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Same start and end NAV returns 0% return."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.5000")),
            make_fund_net_value(nav_date=date(2024, 6, 1), unit_nav=Decimal("1.5000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == pytest.approx(0.0)

    def test_multi_point_series_uses_endpoints(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Only first and last NAV matter for total return."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 6, 1), unit_nav=Decimal("2.0000")),
            make_fund_net_value(nav_date=date(2024, 12, 31), unit_nav=Decimal("1.5000")),
        ]
        result = perf_calculator.calculate_total_return(navs)
        assert result == pytest.approx(50.0)


class TestCalculateAnnualizedReturn:
    """Tests for FundPerformanceCalculator.calculate_annualized_return"""

    def test_one_year_period(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Annualized return equals total return for exactly one year (approx)."""
        # 365 days ~ 1 year (365.25 factor causes slight difference)
        result = perf_calculator.calculate_annualized_return(10.0, 365)
        assert result == pytest.approx(10.0, abs=0.1)

    def test_two_year_period(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Annualized return for 2 years with 21% total is ~10%."""
        # (1.21)^(1/2) - 1 = 0.1 = 10%
        result = perf_calculator.calculate_annualized_return(21.0, 731)
        assert result == pytest.approx(10.0, abs=0.5)

    def test_zero_days(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Zero days returns 0."""
        result = perf_calculator.calculate_annualized_return(10.0, 0)
        assert result == 0.0

    def test_negative_days(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Negative days returns 0."""
        result = perf_calculator.calculate_annualized_return(10.0, -10)
        assert result == 0.0

    def test_zero_return(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Zero total return gives zero annualized return."""
        result = perf_calculator.calculate_annualized_return(0.0, 365)
        assert result == pytest.approx(0.0)

    def test_negative_return(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Negative total return gives negative annualized return."""
        result = perf_calculator.calculate_annualized_return(-10.0, 365)
        assert result < 0


class TestCalculateVolatility:
    """Tests for FundPerformanceCalculator.calculate_volatility"""

    def test_constant_returns_zero_volatility(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Constant daily returns produce zero volatility."""
        daily_returns = [1.0] * 20
        result = perf_calculator.calculate_volatility(daily_returns)
        assert result == pytest.approx(0.0)

    def test_single_return_zero_volatility(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Single return gives 0 volatility."""
        result = perf_calculator.calculate_volatility([1.0])
        assert result == 0.0

    def test_empty_returns_zero_volatility(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Empty list gives 0 volatility."""
        result = perf_calculator.calculate_volatility([])
        assert result == 0.0

    def test_varied_returns_positive_volatility(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Varying daily returns produce positive volatility."""
        daily_returns = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5]
        result = perf_calculator.calculate_volatility(daily_returns)
        assert result > 0

    def test_annualization_factor(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Volatility is annualized with sqrt(252) factor."""
        daily_returns = [1.0, -1.0]
        result = perf_calculator.calculate_volatility(daily_returns)
        # Sample std of [1, -1]: mean=0, variance = (1+1)/(2-1) = 2, std = sqrt(2)
        # Annualized = sqrt(2) * sqrt(252)
        expected = (2 ** 0.5) * (252 ** 0.5)
        assert result == pytest.approx(expected, rel=0.01)


class TestCalculateSharpeRatio:
    """Tests for FundPerformanceCalculator.calculate_sharpe_ratio"""

    def test_positive_sharpe(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Return above risk-free rate gives positive Sharpe."""
        result = perf_calculator.calculate_sharpe_ratio(10.0, 5.0, risk_free_rate=3.0)
        assert result == pytest.approx((10.0 - 3.0) / 5.0)

    def test_negative_sharpe(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Return below risk-free rate gives negative Sharpe."""
        result = perf_calculator.calculate_sharpe_ratio(1.0, 5.0, risk_free_rate=3.0)
        assert result < 0

    def test_zero_volatility(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Zero volatility returns 0 to avoid division by zero."""
        result = perf_calculator.calculate_sharpe_ratio(10.0, 0.0)
        assert result == 0.0

    def test_default_risk_free_rate(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Default risk-free rate is 3%."""
        result = perf_calculator.calculate_sharpe_ratio(13.0, 10.0)
        assert result == pytest.approx(1.0)


class TestCalculateMaxDrawdown:
    """Tests for FundPerformanceCalculator.calculate_max_drawdown"""

    def test_simple_drawdown(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Standard drawdown calculation from peak to trough."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 2, 1), unit_nav=Decimal("1.2000")),
            make_fund_net_value(nav_date=date(2024, 3, 1), unit_nav=Decimal("0.9600")),
            make_fund_net_value(nav_date=date(2024, 4, 1), unit_nav=Decimal("1.1000")),
        ]
        result = perf_calculator.calculate_max_drawdown(navs)
        # Peak = 1.2, trough = 0.96, drawdown = (1.2 - 0.96) / 1.2 * 100 = 20%
        assert result == pytest.approx(20.0)

    def test_monotonically_increasing(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Monotonically increasing NAV has 0 max drawdown."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, i + 1), unit_nav=Decimal(str(1 + i * 0.1)))
            for i in range(5)
        ]
        result = perf_calculator.calculate_max_drawdown(navs)
        assert result == pytest.approx(0.0)

    def test_monotonically_decreasing(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """Monotonically decreasing NAV: drawdown equals total decline %."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("2.0000")),
            make_fund_net_value(nav_date=date(2024, 2, 1), unit_nav=Decimal("1.5000")),
            make_fund_net_value(nav_date=date(2024, 3, 1), unit_nav=Decimal("1.0000")),
        ]
        result = perf_calculator.calculate_max_drawdown(navs)
        # (2.0 - 1.0) / 2.0 * 100 = 50%
        assert result == pytest.approx(50.0)

    def test_single_nav_entry(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Single NAV entry returns 0."""
        navs = [make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.5000"))]
        result = perf_calculator.calculate_max_drawdown(navs)
        assert result == 0.0

    def test_empty_nav_series(self, perf_calculator: FundPerformanceCalculator) -> None:
        """Empty NAV series returns 0."""
        result = perf_calculator.calculate_max_drawdown([])
        assert result == 0.0

    def test_multiple_drawdowns_returns_max(
        self, perf_calculator: FundPerformanceCalculator
    ) -> None:
        """When multiple drawdowns occur, returns the largest one."""
        navs = [
            make_fund_net_value(nav_date=date(2024, 1, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 2, 1), unit_nav=Decimal("1.1000")),
            # 1st drawdown: 1.1 -> 1.0 = 9.09%
            make_fund_net_value(nav_date=date(2024, 3, 1), unit_nav=Decimal("1.0000")),
            make_fund_net_value(nav_date=date(2024, 4, 1), unit_nav=Decimal("1.5000")),
            # 2nd drawdown: 1.5 -> 1.1 = 26.67%
            make_fund_net_value(nav_date=date(2024, 5, 1), unit_nav=Decimal("1.1000")),
            make_fund_net_value(nav_date=date(2024, 6, 1), unit_nav=Decimal("1.4000")),
        ]
        result = perf_calculator.calculate_max_drawdown(navs)
        expected = (1.5 - 1.1) / 1.5 * 100  # ~26.67%
        assert result == pytest.approx(expected, abs=0.01)


# ============================================================
# Internal / Helper Method Tests
# ============================================================


class TestNormalizeScore:
    """Tests for FundScreener._normalize_score"""

    def test_value_at_min(self, screener: FundScreener) -> None:
        """Value at min returns 0."""
        assert screener._normalize_score(0.0, 0.0, 100.0) == pytest.approx(0.0)

    def test_value_at_max(self, screener: FundScreener) -> None:
        """Value at max returns 100."""
        assert screener._normalize_score(100.0, 0.0, 100.0) == pytest.approx(100.0)

    def test_value_at_midpoint(self, screener: FundScreener) -> None:
        """Value at midpoint returns 50."""
        assert screener._normalize_score(50.0, 0.0, 100.0) == pytest.approx(50.0)

    def test_value_below_min_clamped(self, screener: FundScreener) -> None:
        """Value below min is clamped to 0."""
        assert screener._normalize_score(-10.0, 0.0, 100.0) == 0.0

    def test_value_above_max_clamped(self, screener: FundScreener) -> None:
        """Value above max is clamped to 100."""
        assert screener._normalize_score(150.0, 0.0, 100.0) == 100.0

    def test_equal_min_max_returns_fifty(self, screener: FundScreener) -> None:
        """When min == max, returns 50."""
        assert screener._normalize_score(5.0, 5.0, 5.0) == 50.0


class TestCalculateScaleScore:
    """Tests for FundScreener._calculate_scale_score"""

    def test_ideal_range(self, screener: FundScreener) -> None:
        """Scale in 10-100 yi (1e9 - 1e10 yuan) returns 90."""
        assert screener._calculate_scale_score(Decimal("5000000000")) == 90.0  # 50 yi

    def test_too_small(self, screener: FundScreener) -> None:
        """Scale < 1 yi returns 30."""
        assert screener._calculate_scale_score(Decimal("50000000")) == 30.0  # 0.5 yi

    def test_moderately_small(self, screener: FundScreener) -> None:
        """Scale 1-10 yi returns between 50 and 70."""
        score = screener._calculate_scale_score(Decimal("500000000"))  # 5 yi
        assert 50.0 < score < 70.0 + 0.01

    def test_moderately_large(self, screener: FundScreener) -> None:
        """Scale 100-500 yi returns between 50 and 80."""
        score = screener._calculate_scale_score(Decimal("20000000000"))  # 200 yi
        assert 50.0 <= score <= 80.0

    def test_too_large(self, screener: FundScreener) -> None:
        """Scale > 500 yi returns 50."""
        assert screener._calculate_scale_score(Decimal("100000000000")) == 50.0  # 1000 yi

    def test_zero_scale(self, screener: FundScreener) -> None:
        """Zero scale returns 30 (too small)."""
        assert screener._calculate_scale_score(Decimal("0")) == 30.0
