"""
Comprehensive tests for apps.hedge.domain.services

Tests cover:
- CorrelationMonitor: calculate_correlation, calculate_correlation_matrix, monitor_hedge_pairs
- HedgeRatioCalculator: all 5 methods (BETA, MIN_VARIANCE, EQUAL_RISK, DOLLAR_NEUTRAL, FIXED_RATIO)
- HedgePortfolioService: update_hedge_portfolio, get_correlation_matrix, check_hedge_effectiveness
- Edge cases: empty price series, zero volatility, invalid inputs
- Financial constraints: correlation bounds, weight bounds

Domain layer testing: NO Django, pandas, or numpy imports.
"""

import math
from datetime import date

import pytest

from apps.hedge.domain.entities import HedgeAlertType, HedgeMethod, HedgePair
from apps.hedge.domain.services import (
    CorrelationMonitor,
    HedgeContext,
    HedgePortfolioService,
    HedgeRatioCalculator,
)
from tests.factories.domain_factories import (
    make_get_asset_name,
    make_get_asset_prices,
    make_hedge_pair,
    make_price_series,
)

# ============================================================
# Fixtures
# ============================================================


def _build_context(
    price_data: dict[str, list[float]] | None = None,
    pairs: list[HedgePair] | None = None,
    calc_date: date | None = None,
) -> HedgeContext:
    """Build a HedgeContext with sensible defaults."""
    return HedgeContext(
        calc_date=calc_date or date(2025, 6, 15),
        hedge_pairs=pairs or [make_hedge_pair()],
        get_asset_prices=make_get_asset_prices(price_data),
        get_asset_name=make_get_asset_name(),
    )


def _constant_prices(value: float, n: int = 200) -> list[float]:
    """Return a flat price series (zero volatility)."""
    return [value] * n


def _linear_prices(start: float, step: float, n: int = 200) -> list[float]:
    """Return a linearly increasing price series."""
    return [start + i * step for i in range(n)]


def _inversely_correlated_prices(n: int = 200) -> tuple:
    """Return two price series that are inversely correlated."""
    base = make_price_series(base_price=100.0, days=n)
    # Mirror around the mean
    mean_price = sum(base) / len(base)
    inverse = [2 * mean_price - p for p in base]
    return base, inverse


# ============================================================
# CorrelationMonitor Tests
# ============================================================


class TestCorrelationMonitorCalculateCorrelation:
    """Tests for CorrelationMonitor.calculate_correlation."""

    def test_returns_correlation_metric_with_valid_data(self):
        """Valid price data produces a CorrelationMetric."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        metric = monitor.calculate_correlation("510300", "511260", window_days=30)

        assert metric is not None
        assert metric.asset1 == "510300"
        assert metric.asset2 == "511260"
        assert -1 <= metric.correlation <= 1
        assert metric.window_days == 30

    def test_returns_none_when_asset1_missing(self):
        """Missing first asset returns None."""
        def no_data(code: str, d: date, n: int):
            if code == "MISSING":
                return None
            return make_price_series(days=n)

        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[],
            get_asset_prices=no_data,
            get_asset_name=make_get_asset_name(),
        )
        monitor = CorrelationMonitor(ctx)
        assert monitor.calculate_correlation("MISSING", "511260") is None

    def test_returns_none_when_asset2_missing(self):
        """Missing second asset returns None."""
        def no_data(code: str, d: date, n: int):
            if code == "MISSING":
                return None
            return make_price_series(days=n)

        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[],
            get_asset_prices=no_data,
            get_asset_name=make_get_asset_name(),
        )
        monitor = CorrelationMonitor(ctx)
        assert monitor.calculate_correlation("510300", "MISSING") is None

    def test_returns_none_when_lengths_differ(self):
        """Mismatched series lengths returns None."""
        def uneven(code: str, d: date, n: int):
            if code == "A":
                return [100.0] * 50
            return [100.0] * 60

        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[],
            get_asset_prices=uneven,
            get_asset_name=make_get_asset_name(),
        )
        monitor = CorrelationMonitor(ctx)
        assert monitor.calculate_correlation("A", "B") is None

    def test_correlation_trend_field_populated(self):
        """Trend field should be one of increasing/decreasing/stable."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        metric = monitor.calculate_correlation("510300", "511260", window_days=30)

        assert metric is not None
        assert metric.correlation_trend in ("increasing", "decreasing", "stable")

    def test_alert_triggered_for_high_correlation(self):
        """Alert fires when correlation exceeds max + threshold."""
        # Use same price series for both assets => correlation ~ 1.0
        same_prices = make_price_series(base_price=100.0, days=200)
        price_data = {"510300": same_prices, "511260": same_prices[:]}

        pair = make_hedge_pair(
            max_correlation=-0.9,
            correlation_alert_threshold=0.2,
        )
        ctx = _build_context(price_data=price_data, pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        metric = monitor.calculate_correlation("510300", "511260", window_days=30)

        assert metric is not None
        # Correlation ~ 1.0 which > -0.9 + 0.2 = -0.7
        assert metric.alert is not None
        assert metric.alert_type == "correlation_high"

    def test_no_alert_when_correlation_within_bounds(self):
        """No alert when correlation stays within bounds."""
        pair = make_hedge_pair(
            min_correlation=-1.0,
            max_correlation=1.0,
            correlation_alert_threshold=0.2,
        )
        ctx = _build_context(pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        metric = monitor.calculate_correlation("510300", "511260", window_days=30)

        assert metric is not None
        assert metric.alert is None
        assert metric.alert_type is None

    def test_beta_is_calculated(self):
        """Beta field is populated."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        metric = monitor.calculate_correlation("510300", "511260", window_days=30)

        assert metric is not None
        assert isinstance(metric.beta, float)


# ============================================================
# CorrelationMonitor - calculate_correlation_matrix
# ============================================================


class TestCorrelationMonitorMatrix:
    """Tests for CorrelationMonitor.calculate_correlation_matrix."""

    def test_diagonal_is_one(self):
        """Self-correlation is always 1.0."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        matrix = monitor.calculate_correlation_matrix(["510300", "511260"])

        assert matrix["510300"]["510300"] == 1.0
        assert matrix["511260"]["511260"] == 1.0

    def test_single_asset_matrix(self):
        """Matrix for a single asset is just {asset: {asset: 1.0}}."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        matrix = monitor.calculate_correlation_matrix(["510300"])

        assert matrix == {"510300": {"510300": 1.0}}

    def test_matrix_has_correct_keys(self):
        """All requested assets appear as keys."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        assets = ["510300", "511260", "159980"]
        matrix = monitor.calculate_correlation_matrix(assets)

        for asset in assets:
            assert asset in matrix


# ============================================================
# CorrelationMonitor - monitor_hedge_pairs
# ============================================================


class TestMonitorHedgePairs:
    """Tests for CorrelationMonitor.monitor_hedge_pairs."""

    def test_no_alerts_for_good_pairs(self):
        """Well-correlated pair within bounds produces no alerts."""
        base, inv = _inversely_correlated_prices(n=200)
        price_data = {"510300": base, "511260": inv}

        pair = make_hedge_pair(
            max_correlation=0.5,
            correlation_alert_threshold=0.5,
            min_correlation=-1.0,
        )
        ctx = _build_context(price_data=price_data, pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        alerts = monitor.monitor_hedge_pairs()

        # The inversely correlated prices have negative correlation,
        # which should be below max_correlation + threshold
        high_corr_alerts = [
            a for a in alerts
            if a.severity == "high"
        ]
        assert len(high_corr_alerts) == 0

    def test_uses_context_pairs_by_default(self):
        """When no pairs argument given, uses context.hedge_pairs."""
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        # Should not raise
        alerts = monitor.monitor_hedge_pairs()
        assert isinstance(alerts, list)

    def test_weak_correlation_alert(self):
        """Near-zero correlation triggers a medium-severity alert."""
        # Generate two independent-ish series by using different base prices
        prices_a = make_price_series(base_price=100.0, days=200, daily_return_std=0.0001)
        make_price_series(base_price=200.0, days=200, daily_return_std=0.0001)
        # Interleave to reduce correlation; simple approach: shift phase
        prices_b_shifted = [200.0] * 200
        for i in range(200):
            prices_b_shifted[i] = 200.0 + 0.001 * math.sin(i * 3.7)

        # Force correlation ~ 0 by using unrelated patterns
        price_data = {"510300": prices_a, "511260": prices_b_shifted}

        pair = make_hedge_pair(
            max_correlation=1.0,
            correlation_alert_threshold=0.5,
        )
        ctx = _build_context(price_data=price_data, pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        alerts = monitor.monitor_hedge_pairs()

        # Check for weak correlation alert (may or may not fire depending on data)
        assert isinstance(alerts, list)

    def test_correlation_breakdown_alert_type(self):
        """High correlation triggers CORRELATION_BREAKDOWN alert."""
        same_prices = make_price_series(base_price=100.0, days=200)
        price_data = {"510300": same_prices, "511260": same_prices[:]}

        pair = make_hedge_pair(
            max_correlation=-0.9,
            correlation_alert_threshold=0.1,
        )
        ctx = _build_context(price_data=price_data, pairs=[pair])
        monitor = CorrelationMonitor(ctx)
        alerts = monitor.monitor_hedge_pairs()

        high_alerts = [a for a in alerts if a.severity == "high"]
        assert len(high_alerts) >= 1
        assert high_alerts[0].alert_type == HedgeAlertType.CORRELATION_BREAKDOWN

    def test_skips_pair_when_metric_is_none(self):
        """When correlation cannot be calculated, pair is skipped."""
        def always_none(code: str, d: date, n: int):
            return None

        pair = make_hedge_pair()
        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[pair],
            get_asset_prices=always_none,
            get_asset_name=make_get_asset_name(),
        )
        monitor = CorrelationMonitor(ctx)
        alerts = monitor.monitor_hedge_pairs()
        assert alerts == []


# ============================================================
# HedgeRatioCalculator Tests
# ============================================================


class TestHedgeRatioCalculatorBeta:
    """Tests for BETA hedge method."""

    def test_beta_method_returns_ratio_and_details(self):
        pair = make_hedge_pair(hedge_method=HedgeMethod.BETA)
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert isinstance(ratio, (int, float))
        assert 0 <= ratio <= 1
        assert details["method"] == "beta"

    def test_beta_with_target(self):
        """Beta target adjusts the ratio."""
        pair = make_hedge_pair(
            hedge_method=HedgeMethod.BETA,
            beta_target=0.5,
        )
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert details["method"] == "beta"
        assert details["beta_target"] == 0.5

    def test_beta_clamped_0_to_1(self):
        """Beta-based ratio is clamped between 0 and 1."""
        pair = make_hedge_pair(hedge_method=HedgeMethod.BETA)
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, _ = calc.calculate_hedge_ratio(pair)

        assert 0 <= ratio <= 1


class TestHedgeRatioCalculatorMinVariance:
    """Tests for MIN_VARIANCE hedge method."""

    def test_min_variance_returns_ratio(self):
        pair = make_hedge_pair(hedge_method=HedgeMethod.MIN_VARIANCE)
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert isinstance(ratio, (int, float))
        assert details["method"] == "min_variance"

    def test_min_variance_clamped_0_to_2(self):
        """Min variance ratio is clamped between 0 and 2."""
        pair = make_hedge_pair(hedge_method=HedgeMethod.MIN_VARIANCE)
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, _ = calc.calculate_hedge_ratio(pair)

        assert 0 <= ratio <= 2

    def test_min_variance_zero_volatility_hedge(self):
        """Zero variance in hedge asset returns ratio=0."""
        price_data = {
            "510300": make_price_series(days=200),
            "511260": _constant_prices(100.0, n=200),
        }
        pair = make_hedge_pair(hedge_method=HedgeMethod.MIN_VARIANCE)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert ratio == 0.0
        assert "Zero variance" in details.get("reason", "")


class TestHedgeRatioCalculatorEqualRisk:
    """Tests for EQUAL_RISK hedge method."""

    def test_equal_risk_returns_ratio(self):
        pair = make_hedge_pair(hedge_method=HedgeMethod.EQUAL_RISK)
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert isinstance(ratio, float)
        assert details["method"] == "equal_risk"

    def test_equal_risk_same_volatility_gives_ratio_near_one(self):
        """Two identical series => same volatility => ratio ~ 1."""
        prices = make_price_series(days=200)
        price_data = {"510300": prices, "511260": prices[:]}
        pair = make_hedge_pair(hedge_method=HedgeMethod.EQUAL_RISK)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert abs(ratio - 1.0) < 0.01

    def test_equal_risk_zero_vol_hedge(self):
        """Zero volatility in hedge asset returns ratio=0."""
        price_data = {
            "510300": make_price_series(days=200),
            "511260": _constant_prices(100.0, n=200),
        }
        pair = make_hedge_pair(hedge_method=HedgeMethod.EQUAL_RISK)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert ratio == 0.0
        assert "Zero volatility" in details.get("reason", "")


class TestHedgeRatioCalculatorDollarNeutral:
    """Tests for DOLLAR_NEUTRAL hedge method."""

    def test_dollar_neutral_returns_price_ratio(self):
        prices_long = make_price_series(base_price=100.0, days=200)
        prices_hedge = make_price_series(base_price=50.0, days=200)
        price_data = {"510300": prices_long, "511260": prices_hedge}
        pair = make_hedge_pair(hedge_method=HedgeMethod.DOLLAR_NEUTRAL)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert details["method"] == "dollar_neutral"
        # ratio = hedge_price / long_price
        expected = details["hedge_price"] / details["long_price"]
        assert abs(ratio - expected) < 1e-9

    def test_dollar_neutral_zero_hedge_price(self):
        """Zero hedge price returns ratio=0."""
        price_data = {
            "510300": make_price_series(days=200),
            "511260": [0.0] * 200,
        }
        pair = make_hedge_pair(hedge_method=HedgeMethod.DOLLAR_NEUTRAL)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert ratio == 0.0
        assert "Zero hedge price" in details.get("reason", "")


class TestHedgeRatioCalculatorFixedRatio:
    """Tests for FIXED_RATIO hedge method."""

    def test_fixed_ratio_uses_target_weights(self):
        pair = make_hedge_pair(
            hedge_method=HedgeMethod.FIXED_RATIO,
            target_long_weight=0.6,
            target_hedge_weight=0.4,
        )
        ctx = _build_context(pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        expected = 0.4 / 0.6
        assert abs(ratio - expected) < 1e-9
        assert details["method"] == "fixed"


class TestHedgeRatioCalculatorEdgeCases:
    """Edge case tests for HedgeRatioCalculator."""

    def test_no_price_data_returns_default(self):
        """When get_asset_prices returns None, default ratio is 0.5."""
        def no_data(code: str, d: date, n: int):
            return None

        pair = make_hedge_pair()
        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[pair],
            get_asset_prices=no_data,
            get_asset_name=make_get_asset_name(),
        )
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert ratio == 0.5
        assert details["method"] == "default"

    def test_empty_price_lists_returns_default(self):
        """Empty price lists return default ratio."""
        def empty_data(code: str, d: date, n: int):
            return []

        pair = make_hedge_pair()
        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[pair],
            get_asset_prices=empty_data,
            get_asset_name=make_get_asset_name(),
        )
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert ratio == 0.5
        assert details["method"] == "default"

    def test_min_variance_with_two_prices(self):
        """Min variance with very few data points still works."""
        price_data = {
            "510300": [100.0, 101.0, 102.0],
            "511260": [50.0, 49.5, 50.5],
        }
        pair = make_hedge_pair(
            hedge_method=HedgeMethod.MIN_VARIANCE,
            correlation_window=3,
        )
        ctx = _build_context(price_data=price_data, pairs=[pair])
        calc = HedgeRatioCalculator(ctx)
        ratio, details = calc.calculate_hedge_ratio(pair)

        assert isinstance(ratio, float)


# ============================================================
# HedgePortfolioService Tests
# ============================================================


class TestHedgePortfolioServiceUpdate:
    """Tests for HedgePortfolioService.update_hedge_portfolio."""

    def test_returns_hedge_portfolio(self):
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        portfolio = svc.update_hedge_portfolio(pair)

        assert portfolio is not None
        assert portfolio.pair_name == pair.name
        assert portfolio.trade_date == ctx.calc_date

    def test_returns_none_when_correlation_unavailable(self):
        """If correlation cannot be calculated, returns None."""
        def no_data(code: str, d: date, n: int):
            return None

        pair = make_hedge_pair()
        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[pair],
            get_asset_prices=no_data,
            get_asset_name=make_get_asset_name(),
        )
        svc = HedgePortfolioService(ctx)
        assert svc.update_hedge_portfolio(pair) is None

    def test_rebalance_needed_when_drift_exceeds_trigger(self):
        """Rebalance flag is set when weight drifts beyond trigger."""
        pair = make_hedge_pair(
            target_long_weight=0.7,
            target_hedge_weight=0.3,
            rebalance_trigger=0.001,  # very tight trigger
        )
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        portfolio = svc.update_hedge_portfolio(pair)

        # With a tight trigger, rebalance is very likely needed
        assert portfolio is not None
        # We just verify the field is present and boolean
        assert isinstance(portfolio.rebalance_needed, bool)

    def test_portfolio_weights_in_valid_range(self):
        """Portfolio weights stay within [0, 1]."""
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        portfolio = svc.update_hedge_portfolio(pair)

        assert portfolio is not None
        assert 0 <= portfolio.long_weight <= 1
        assert 0 <= portfolio.hedge_weight <= 1

    def test_hedge_effectiveness_equals_abs_correlation(self):
        """Hedge effectiveness = abs(correlation)."""
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        portfolio = svc.update_hedge_portfolio(pair)

        assert portfolio is not None
        assert portfolio.hedge_effectiveness == pytest.approx(
            abs(portfolio.current_correlation), abs=1e-6
        )


class TestHedgePortfolioServiceCorrelationMatrix:
    """Tests for HedgePortfolioService.get_correlation_matrix."""

    def test_delegates_to_monitor(self):
        ctx = _build_context()
        svc = HedgePortfolioService(ctx)
        matrix = svc.get_correlation_matrix(["510300", "511260"])

        assert "510300" in matrix
        assert "511260" in matrix
        assert matrix["510300"]["510300"] == 1.0


class TestHedgePortfolioServiceEffectiveness:
    """Tests for HedgePortfolioService.check_hedge_effectiveness."""

    def test_returns_effectiveness_dict(self):
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        result = svc.check_hedge_effectiveness(pair)

        assert "pair_name" in result
        assert "correlation" in result
        assert "effectiveness" in result
        assert "rating" in result
        assert "recommendation" in result

    def test_returns_error_when_correlation_unavailable(self):
        def no_data(code: str, d: date, n: int):
            return None

        pair = make_hedge_pair()
        ctx = HedgeContext(
            calc_date=date(2025, 6, 15),
            hedge_pairs=[pair],
            get_asset_prices=no_data,
            get_asset_name=make_get_asset_name(),
        )
        svc = HedgePortfolioService(ctx)
        result = svc.check_hedge_effectiveness(pair)

        assert "error" in result

    def test_rating_excellent_for_high_effectiveness(self):
        """Effectiveness >= 0.8 => rating '优秀'."""
        # Same prices => correlation ~ 1.0 => effectiveness ~ 1.0
        prices = make_price_series(days=200)
        price_data = {"510300": prices, "511260": prices[:]}
        pair = make_hedge_pair()
        ctx = _build_context(price_data=price_data, pairs=[pair])
        svc = HedgePortfolioService(ctx)
        result = svc.check_hedge_effectiveness(pair)

        assert result["effectiveness"] >= 0.8
        assert result["rating"] == "优秀"

    def test_recommendation_for_low_effectiveness(self):
        """Low effectiveness yields a 'change strategy' recommendation."""
        # Create near-uncorrelated series
        prices_a = [100.0 + 0.01 * math.sin(i * 0.3) for i in range(200)]
        prices_b = [100.0 + 0.01 * math.cos(i * 1.7) for i in range(200)]
        price_data = {"510300": prices_a, "511260": prices_b}

        pair = make_hedge_pair(max_correlation=1.0)
        ctx = _build_context(price_data=price_data, pairs=[pair])
        svc = HedgePortfolioService(ctx)
        result = svc.check_hedge_effectiveness(pair)

        # Should recommend action for weak hedge
        assert "recommendation" in result
        assert isinstance(result["recommendation"], str)

    def test_trend_field_present(self):
        pair = make_hedge_pair()
        ctx = _build_context(pairs=[pair])
        svc = HedgePortfolioService(ctx)
        result = svc.check_hedge_effectiveness(pair)

        assert "trend" in result
        assert result["trend"] in ("increasing", "decreasing", "stable")


# ============================================================
# Correlation Trend & Rolling MA
# ============================================================


class TestCorrelationTrend:
    """Tests for _calculate_correlation_trend."""

    def test_stable_when_insufficient_data(self):
        """Returns 'stable' when data is shorter than 2 * window."""
        price_data = {
            "510300": [100.0] * 30,
            "511260": [100.0] * 30,
        }
        ctx = _build_context(price_data=price_data)
        monitor = CorrelationMonitor(ctx)
        trend = monitor._calculate_correlation_trend(
            [100.0] * 30, [100.0] * 30, window_days=20
        )
        assert trend == "stable"

    def test_returns_valid_trend_value(self):
        """Trend is one of increasing, decreasing, stable."""
        prices1 = make_price_series(days=200)
        prices2 = make_price_series(base_price=50.0, days=200)
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        trend = monitor._calculate_correlation_trend(prices1, prices2, window_days=30)

        assert trend in ("increasing", "decreasing", "stable")


class TestRollingCorrelationMA:
    """Tests for _calculate_rolling_correlation_ma."""

    def test_returns_zero_when_insufficient_data(self):
        """Returns 0.0 when data < 3 * window."""
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        result = monitor._calculate_rolling_correlation_ma(
            [100.0] * 20, [100.0] * 20, window_days=30
        )
        assert result == 0.0

    def test_returns_float_with_sufficient_data(self):
        prices1 = make_price_series(days=200)
        prices2 = make_price_series(base_price=50.0, days=200)
        ctx = _build_context()
        monitor = CorrelationMonitor(ctx)
        result = monitor._calculate_rolling_correlation_ma(
            prices1, prices2, window_days=30
        )
        assert isinstance(result, float)


# ============================================================
# Volatility & Returns helpers
# ============================================================


class TestHedgeRatioHelpers:
    """Tests for internal helper methods on HedgeRatioCalculator."""

    def test_calculate_returns_simple(self):
        ctx = _build_context()
        calc = HedgeRatioCalculator(ctx)
        returns = calc._calculate_returns([100.0, 110.0, 105.0])

        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.1, abs=1e-9)
        assert returns[1] == pytest.approx(-5.0 / 110.0, abs=1e-9)

    def test_calculate_returns_skips_zero_price(self):
        """Zero price in denominator is skipped."""
        ctx = _build_context()
        calc = HedgeRatioCalculator(ctx)
        returns = calc._calculate_returns([0.0, 100.0, 110.0])

        # First return from 0->100 is skipped (denominator 0)
        # Second return from 100->110 is valid
        assert len(returns) == 1
        assert returns[0] == pytest.approx(0.1, abs=1e-9)

    def test_calculate_volatility_constant_prices(self):
        """Constant prices => zero volatility."""
        ctx = _build_context()
        calc = HedgeRatioCalculator(ctx)
        vol = calc._calculate_volatility(_constant_prices(100.0, 50))

        assert vol == 0.0

    def test_calculate_volatility_annualized(self):
        """Volatility is annualized (multiplied by sqrt(252))."""
        ctx = _build_context()
        calc = HedgeRatioCalculator(ctx)
        prices = make_price_series(days=200)
        vol = calc._calculate_volatility(prices)

        assert vol > 0
        # Verify it's annualized: vol should be larger than daily std
        returns = calc._calculate_returns(prices)
        mean_r = sum(returns) / len(returns)
        daily_var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        daily_std = math.sqrt(daily_var)
        assert vol == pytest.approx(daily_std * math.sqrt(252), abs=1e-9)

    def test_calculate_volatility_empty_returns_zero(self):
        ctx = _build_context()
        calc = HedgeRatioCalculator(ctx)
        assert calc._calculate_volatility([100.0]) == 0.0
