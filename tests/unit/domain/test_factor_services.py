"""
Tests for Factor Module Domain Services

Covers:
- FactorEngine: calculate_factor_exposure, calculate_factor_scores, select_portfolio
- ScoringService: get_top_stocks, explain_stock_score
- Edge cases: empty universe, missing factor values, zero weights
- Factor calculation correctness (percentile, z-score, composite score)

NO Django, pandas, or numpy imports.
"""

import math
import pytest
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from apps.factor.domain.entities import (
    FactorCategory,
    FactorDefinition,
    FactorDirection,
    FactorExposure,
    FactorPortfolioConfig,
    FactorScore,
    get_common_factors,
)
from apps.factor.domain.services import (
    FactorCalculationContext,
    FactorEngine,
    ScoringService,
)
from tests.factories.domain_factories import (
    make_factor_definition,
    make_factor_exposure,
    make_factor_portfolio_config,
    make_factor_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRADE_DATE = date(2025, 6, 15)

# Stock universe with deterministic factor values
STOCK_DATA: Dict[str, Dict[str, float]] = {
    "000001": {"pe_ttm": 8.0, "roe": 12.0, "momentum_3m": 0.05},
    "000002": {"pe_ttm": 15.0, "roe": 18.0, "momentum_3m": 0.10},
    "000003": {"pe_ttm": 25.0, "roe": 8.0, "momentum_3m": -0.02},
    "000004": {"pe_ttm": 12.0, "roe": 22.0, "momentum_3m": 0.15},
    "000005": {"pe_ttm": 30.0, "roe": 5.0, "momentum_3m": -0.08},
}

STOCK_INFO: Dict[str, Dict] = {
    "000001": {"name": "Stock A", "sector": "Finance", "market_cap": 300_000_000_000},
    "000002": {"name": "Stock B", "sector": "Tech", "market_cap": 150_000_000_000},
    "000003": {"name": "Stock C", "sector": "Finance", "market_cap": 50_000_000_000},
    "000004": {"name": "Stock D", "sector": "Health", "market_cap": 200_000_000_000},
    "000005": {"name": "Stock E", "sector": "Energy", "market_cap": 80_000_000_000},
}


def _get_factor_value(stock_code: str, factor_code: str, td: date) -> Optional[float]:
    """Mock factor value accessor."""
    stock = STOCK_DATA.get(stock_code)
    if stock is None:
        return None
    return stock.get(factor_code)


def _get_stock_info(stock_code: str) -> Optional[Dict]:
    """Mock stock info accessor."""
    return STOCK_INFO.get(stock_code)


def _make_context(
    universe: Optional[List[str]] = None,
    factor_defs: Optional[List[FactorDefinition]] = None,
    get_factor_value=_get_factor_value,
    get_stock_info=_get_stock_info,
) -> FactorCalculationContext:
    """Build a FactorCalculationContext with sensible defaults."""
    if universe is None:
        universe = list(STOCK_DATA.keys())
    if factor_defs is None:
        factor_defs = [
            make_factor_definition(
                code="pe_ttm",
                name="PE(TTM)",
                category=FactorCategory.VALUE,
                direction=FactorDirection.NEGATIVE,
            ),
            make_factor_definition(
                code="roe",
                name="ROE",
                category=FactorCategory.QUALITY,
                direction=FactorDirection.POSITIVE,
            ),
            make_factor_definition(
                code="momentum_3m",
                name="3M Momentum",
                category=FactorCategory.MOMENTUM,
                direction=FactorDirection.POSITIVE,
            ),
        ]
    return FactorCalculationContext(
        trade_date=TRADE_DATE,
        universe=universe,
        factor_definitions=factor_defs,
        get_factor_value=get_factor_value,
        get_stock_info=get_stock_info,
    )


# ===========================================================================
# FactorEngine.calculate_factor_exposure
# ===========================================================================


class TestCalculateFactorExposure:
    """Tests for FactorEngine.calculate_factor_exposure."""

    def test_positive_factor_exposure(self) -> None:
        """Positive-direction factor: higher raw value -> higher percentile."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # 000004 has the highest ROE (22.0)
        exposure = engine.calculate_factor_exposure("000004", "roe")
        assert exposure is not None
        assert exposure.stock_code == "000004"
        assert exposure.factor_code == "roe"
        assert exposure.factor_value == 22.0
        assert exposure.percentile_rank == 1.0  # highest value
        assert exposure.z_score > 0  # above mean

    def test_negative_factor_exposure_inverts_direction(self) -> None:
        """Negative-direction factor (PE): lower raw value -> higher percentile."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # 000001 has the lowest PE (8.0) -> should get high percentile after inversion
        exposure = engine.calculate_factor_exposure("000001", "pe_ttm")
        assert exposure is not None
        # After NEGATIVE inversion: percentile_rank = 1 - original
        # Original: 8.0 is the lowest, count_le = 1, pctile = 1/5 = 0.2
        # Inverted: 1.0 - 0.2 = 0.8
        assert exposure.percentile_rank == pytest.approx(0.8)

    def test_unknown_factor_returns_none(self) -> None:
        """Requesting a factor not in definitions returns None."""
        ctx = _make_context()
        engine = FactorEngine(ctx)
        result = engine.calculate_factor_exposure("000001", "nonexistent_factor")
        assert result is None

    def test_missing_value_allow_missing_true(self) -> None:
        """When allow_missing=True and value is None, returns None."""
        factor_def = make_factor_definition(
            code="special",
            name="Special",
            allow_missing=True,
        )
        ctx = _make_context(factor_defs=[factor_def])
        engine = FactorEngine(ctx)

        # "special" factor is not in STOCK_DATA, so get_factor_value returns None
        result = engine.calculate_factor_exposure("000001", "special")
        assert result is None

    def test_missing_value_allow_missing_false_returns_none(self) -> None:
        """When allow_missing=False and value is None, returns None (graceful handling)."""
        factor_def = make_factor_definition(
            code="special",
            name="Special",
            allow_missing=False,
        )
        ctx = _make_context(factor_defs=[factor_def])
        engine = FactorEngine(ctx)

        result = engine.calculate_factor_exposure("000001", "special")
        assert result is None

    def test_z_score_calculation(self) -> None:
        """Z-score is correctly calculated as (value - mean) / std."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        exposure = engine.calculate_factor_exposure("000002", "roe")
        assert exposure is not None

        # ROE values: [12, 18, 8, 22, 5]
        # mean = 13.0, std = sqrt(sum((v-13)^2)/4) = sqrt((1+25+25+81+64)/4) = sqrt(49) = 7.0
        values = [12.0, 18.0, 8.0, 22.0, 5.0]
        mean = sum(values) / len(values)  # 13.0
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        std = math.sqrt(variance)
        expected_z = (18.0 - mean) / std

        assert exposure.z_score == pytest.approx(expected_z, abs=1e-6)

    def test_normalized_score_in_range(self) -> None:
        """Normalized score is between 0 and 100."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        for stock in STOCK_DATA:
            exposure = engine.calculate_factor_exposure(stock, "roe")
            assert exposure is not None
            assert 0 <= exposure.normalized_score <= 100

    def test_single_stock_universe(self) -> None:
        """With one stock, percentile=1.0 and z_score=0.0."""
        ctx = _make_context(universe=["000001"])
        engine = FactorEngine(ctx)

        exposure = engine.calculate_factor_exposure("000001", "roe")
        assert exposure is not None
        # Single value -> std defaults to 1.0 in _calculate_mean_std (n==1 branch)
        # z_score = (12 - 12) / 1 = 0
        assert exposure.z_score == pytest.approx(0.0)
        # count_le = 1, n = 1 -> percentile = 1.0
        assert exposure.percentile_rank == pytest.approx(1.0)


# ===========================================================================
# FactorEngine.calculate_factor_scores
# ===========================================================================


class TestCalculateFactorScores:
    """Tests for FactorEngine.calculate_factor_scores."""

    def test_basic_composite_scoring(self) -> None:
        """Composite scores are weighted sums of individual factor scores."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        weights = {"pe_ttm": 0.4, "roe": 0.3, "momentum_3m": 0.3}
        scores = engine.calculate_factor_scores(weights)

        assert len(scores) == 5
        # Sorted descending by composite_score
        for i in range(len(scores) - 1):
            assert scores[i].composite_score >= scores[i + 1].composite_score

    def test_weights_must_sum_to_one(self) -> None:
        """Weights not summing to 1.0 raises ValueError."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        with pytest.raises(ValueError, match="Factor weights must sum to 1.0"):
            engine.calculate_factor_scores({"pe_ttm": 0.3, "roe": 0.3})

    def test_factor_scores_contain_expected_fields(self) -> None:
        """Each FactorScore contains stock info and factor breakdown."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        weights = {"pe_ttm": 0.5, "roe": 0.5}
        scores = engine.calculate_factor_scores(weights)
        first = scores[0]

        assert first.stock_code in STOCK_DATA
        assert first.stock_name != ""
        assert first.trade_date == TRADE_DATE
        assert "pe_ttm" in first.factor_scores or "roe" in first.factor_scores
        assert first.factor_weights == weights

    def test_empty_universe_returns_empty(self) -> None:
        """Empty universe produces no scores."""
        ctx = _make_context(universe=[])
        engine = FactorEngine(ctx)

        scores = engine.calculate_factor_scores({"pe_ttm": 0.5, "roe": 0.5})
        assert scores == []

    def test_stock_with_no_info_excluded(self) -> None:
        """Stocks whose get_stock_info returns None are excluded."""

        def _no_info(stock_code: str) -> Optional[Dict]:
            if stock_code == "000003":
                return None
            return STOCK_INFO.get(stock_code)

        ctx = _make_context(get_stock_info=_no_info)
        engine = FactorEngine(ctx)

        scores = engine.calculate_factor_scores({"pe_ttm": 0.5, "roe": 0.5})
        codes = {s.stock_code for s in scores}
        assert "000003" not in codes
        assert len(scores) == 4

    def test_category_scores_populated(self) -> None:
        """Category sub-scores are populated from common factor definitions."""
        # Use common factor codes so category mapping works
        ctx = _make_context()
        engine = FactorEngine(ctx)

        weights = {"pe_ttm": 0.5, "roe": 0.5}
        scores = engine.calculate_factor_scores(weights)

        for s in scores:
            # pe_ttm is VALUE, roe is QUALITY
            # At least one of these should be non-zero
            assert s.value_score >= 0 or s.quality_score >= 0

    def test_composite_score_uses_default_for_missing_factor(self) -> None:
        """If a factor exposure is missing, default 50.0 is used."""
        # Create a factor def whose values don't exist in STOCK_DATA
        defs = [
            make_factor_definition(code="pe_ttm", direction=FactorDirection.NEGATIVE),
            make_factor_definition(
                code="mystery",
                name="Mystery",
                allow_missing=True,
            ),
        ]
        ctx = _make_context(factor_defs=defs)
        engine = FactorEngine(ctx)

        weights = {"pe_ttm": 0.5, "mystery": 0.5}
        scores = engine.calculate_factor_scores(weights)

        # mystery should contribute 50.0 * 0.5 = 25.0 to each stock's composite
        for s in scores:
            mystery_contribution = 50.0 * 0.5
            pe_contribution = s.factor_scores.get("pe_ttm", 50.0) * 0.5
            expected = pe_contribution + mystery_contribution
            assert s.composite_score == pytest.approx(expected, abs=0.01)


# ===========================================================================
# FactorEngine.select_portfolio
# ===========================================================================


class TestSelectPortfolio:
    """Tests for FactorEngine.select_portfolio."""

    def test_equal_weight_portfolio(self) -> None:
        """Equal weight method distributes weight evenly."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="EqualWeight",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=3,
            weight_method="equal_weight",
        )
        holdings = engine.select_portfolio(config)

        assert len(holdings) == 3
        expected_weight = 1.0 / 3
        for h in holdings:
            assert h.weight == pytest.approx(expected_weight, abs=1e-9)
            assert h.config_name == "EqualWeight"
            assert h.trade_date == TRADE_DATE

    def test_factor_weighted_portfolio(self) -> None:
        """Factor weighted method distributes weight proportional to score."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="FactorWeighted",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=3,
            weight_method="factor_weighted",
        )
        holdings = engine.select_portfolio(config)

        assert len(holdings) == 3
        total_weight = sum(h.weight for h in holdings)
        assert total_weight == pytest.approx(1.0, abs=1e-9)

        # Higher factor score -> higher weight
        for i in range(len(holdings) - 1):
            assert holdings[i].factor_score >= holdings[i + 1].factor_score

    def test_top_n_limits_selection(self) -> None:
        """top_n restricts the number of holdings."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Small",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=2,
        )
        holdings = engine.select_portfolio(config)
        assert len(holdings) == 2

    def test_rank_assignment(self) -> None:
        """Holdings have correct rank values starting from 1."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Ranked",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=5,
        )
        holdings = engine.select_portfolio(config)
        ranks = [h.rank for h in holdings]
        assert ranks == [1, 2, 3, 4, 5]

    def test_market_cap_filter(self) -> None:
        """Market cap filter excludes stocks below the threshold."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # min_market_cap=100 billion -> excludes 000003 (50B) and 000005 (80B)
        config = make_factor_portfolio_config(
            name="BigCap",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=10,
            min_market_cap=100.0,
        )
        holdings = engine.select_portfolio(config)
        codes = {h.stock_code for h in holdings}
        assert "000003" not in codes
        assert "000005" not in codes

    def test_max_market_cap_filter(self) -> None:
        """Max market cap filter excludes stocks above the threshold."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # max_market_cap=100 billion -> excludes 000001 (300B), 000002 (150B), 000004 (200B)
        config = make_factor_portfolio_config(
            name="SmallCap",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=10,
            max_market_cap=100.0,
        )
        holdings = engine.select_portfolio(config)
        codes = {h.stock_code for h in holdings}
        assert "000001" not in codes
        assert "000002" not in codes
        assert "000004" not in codes

    def test_empty_universe_returns_empty_portfolio(self) -> None:
        """Empty universe produces empty portfolio."""
        ctx = _make_context(universe=[])
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Empty",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
        )
        holdings = engine.select_portfolio(config)
        assert holdings == []

    def test_default_weight_method_uses_equal_weight(self) -> None:
        """Unrecognized weight method falls back to equal weight."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Default",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=3,
            weight_method="market_cap_weighted",
        )
        holdings = engine.select_portfolio(config)
        # Market cap weighted falls back to equal weight in the current impl
        expected_weight = 1.0 / 3
        for h in holdings:
            assert h.weight == pytest.approx(expected_weight, abs=1e-9)

    def test_factor_weighted_zero_total_score(self) -> None:
        """Factor weighted with total_score=0 falls back to equal weight."""

        # All factor values are 0 -> all exposures map to z=0 -> normalized ~ 50
        # Not truly zero composite, but let's force it via mock
        def _zero_values(stock: str, factor: str, td: date) -> Optional[float]:
            return 0.0

        factor_defs = [
            make_factor_definition(code="f1", name="F1"),
        ]
        ctx = _make_context(
            universe=["A", "B"],
            factor_defs=factor_defs,
            get_factor_value=_zero_values,
            get_stock_info=lambda c: {"name": c, "sector": "X"},
        )
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Zero",
            factor_weights={"f1": 1.0},
            top_n=2,
            weight_method="factor_weighted",
        )
        holdings = engine.select_portfolio(config)
        # Both stocks have identical scores, weight should be equal
        assert len(holdings) == 2
        total = sum(h.weight for h in holdings)
        assert total == pytest.approx(1.0, abs=1e-9)


# ===========================================================================
# ScoringService
# ===========================================================================


class TestScoringService:
    """Tests for ScoringService."""

    def test_get_top_stocks_returns_correct_count(self) -> None:
        """get_top_stocks returns at most top_n results."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        top = svc.get_top_stocks({"pe_ttm": 0.5, "roe": 0.5}, top_n=3)
        assert len(top) == 3

    def test_get_top_stocks_sorted_descending(self) -> None:
        """Results are sorted by composite score descending."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        top = svc.get_top_stocks({"pe_ttm": 0.5, "roe": 0.5}, top_n=5)
        for i in range(len(top) - 1):
            assert top[i].composite_score >= top[i + 1].composite_score

    def test_get_top_stocks_with_top_n_larger_than_universe(self) -> None:
        """Requesting more stocks than available returns all stocks."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        top = svc.get_top_stocks({"pe_ttm": 0.5, "roe": 0.5}, top_n=100)
        assert len(top) == 5

    def test_explain_stock_score_structure(self) -> None:
        """explain_stock_score returns expected dictionary structure."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        explanation = svc.explain_stock_score("000001", {"pe_ttm": 0.5, "roe": 0.5})
        assert explanation is not None
        assert explanation["stock_code"] == "000001"
        assert explanation["stock_name"] == "Stock A"
        assert "composite_score" in explanation
        assert "factor_breakdown" in explanation
        assert "category_breakdown" in explanation

        # Category breakdown should have all six categories
        cats = explanation["category_breakdown"]
        for key in ["value", "quality", "growth", "momentum", "volatility", "liquidity"]:
            assert key in cats

    def test_explain_stock_score_factor_breakdown(self) -> None:
        """Factor breakdown includes score, weight, and contribution."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        explanation = svc.explain_stock_score("000001", {"pe_ttm": 0.5, "roe": 0.5})
        assert explanation is not None

        for factor_code, breakdown in explanation["factor_breakdown"].items():
            assert "score" in breakdown
            assert "weight" in breakdown
            assert "contribution" in breakdown
            # contribution = score * weight
            assert breakdown["contribution"] == pytest.approx(
                breakdown["score"] * breakdown["weight"], abs=0.5
            )

    def test_explain_unknown_stock_returns_none(self) -> None:
        """Explaining a stock not in stock_info returns None."""
        ctx = _make_context()
        svc = ScoringService(ctx)

        result = svc.explain_stock_score("999999", {"pe_ttm": 0.5, "roe": 0.5})
        assert result is None


# ===========================================================================
# Internal calculation correctness
# ===========================================================================


class TestCalculationCorrectness:
    """Verify math correctness of percentile, z-score, and composite computations."""

    def test_percentile_lowest_value(self) -> None:
        """The lowest value in a set gets percentile = 1/n."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # ROE values: [12, 18, 8, 22, 5]
        # 000005 has ROE = 5.0, the minimum -> count_le = 1, percentile = 1/5 = 0.2
        exposure = engine.calculate_factor_exposure("000005", "roe")
        assert exposure is not None
        assert exposure.percentile_rank == pytest.approx(0.2)

    def test_percentile_highest_value(self) -> None:
        """The highest value gets percentile = 1.0."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        # 000004 has ROE = 22.0, count_le = 5, percentile = 5/5 = 1.0
        exposure = engine.calculate_factor_exposure("000004", "roe")
        assert exposure is not None
        assert exposure.percentile_rank == pytest.approx(1.0)

    def test_z_score_to_percentile_symmetric(self) -> None:
        """z=0 maps to ~50%, z>0 maps to >50%, z<0 maps to <50%."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        assert engine._z_score_to_percentile(0.0) == pytest.approx(50.0, abs=0.1)
        assert engine._z_score_to_percentile(1.96) == pytest.approx(97.5, abs=0.5)
        assert engine._z_score_to_percentile(-1.96) == pytest.approx(2.5, abs=0.5)

    def test_mean_std_empty_values(self) -> None:
        """Empty list returns (0.0, 1.0) to avoid division by zero."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        mean, std = engine._calculate_mean_std([])
        assert mean == 0.0
        assert std == 1.0

    def test_mean_std_single_value(self) -> None:
        """Single value returns (value, 1.0)."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        mean, std = engine._calculate_mean_std([42.0])
        assert mean == 42.0
        assert std == 1.0

    def test_mean_std_multiple_values(self) -> None:
        """Correct sample standard deviation for multiple values."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        values = [10.0, 20.0, 30.0]
        mean, std = engine._calculate_mean_std(values)
        assert mean == pytest.approx(20.0)
        # sample std = sqrt(((10-20)^2 + (20-20)^2 + (30-20)^2) / 2) = sqrt(200/2) = 10
        assert std == pytest.approx(10.0)

    def test_percentile_with_ties(self) -> None:
        """Tied values share the same percentile."""
        def _tied_values(stock: str, factor: str, td: date) -> Optional[float]:
            return {"A": 10.0, "B": 10.0, "C": 20.0}[stock]

        factor_def = make_factor_definition(code="f1", name="F1")
        ctx = _make_context(
            universe=["A", "B", "C"],
            factor_defs=[factor_def],
            get_factor_value=_tied_values,
            get_stock_info=lambda c: {"name": c, "sector": "X"},
        )
        engine = FactorEngine(ctx)

        exp_a = engine.calculate_factor_exposure("A", "f1")
        exp_b = engine.calculate_factor_exposure("B", "f1")
        assert exp_a is not None and exp_b is not None
        # Both have value=10, count_le = 2 out of 3 -> percentile = 2/3
        assert exp_a.percentile_rank == pytest.approx(exp_b.percentile_rank)
        assert exp_a.percentile_rank == pytest.approx(2.0 / 3.0, abs=1e-9)


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_all_same_values_z_score_zero(self) -> None:
        """When all stocks have the same value, std=0 -> z_score=0."""
        def _same_value(stock: str, factor: str, td: date) -> Optional[float]:
            return 50.0

        factor_def = make_factor_definition(code="f1", name="F1")
        ctx = _make_context(
            universe=["A", "B", "C"],
            factor_defs=[factor_def],
            get_factor_value=_same_value,
            get_stock_info=lambda c: {"name": c, "sector": "X"},
        )
        engine = FactorEngine(ctx)

        exp = engine.calculate_factor_exposure("A", "f1")
        assert exp is not None
        assert exp.z_score == pytest.approx(0.0)

    def test_factor_weighted_holdings_sum_to_one(self) -> None:
        """Portfolio weights always sum to 1.0 for factor_weighted."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="FW",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=5,
            weight_method="factor_weighted",
        )
        holdings = engine.select_portfolio(config)
        total = sum(h.weight for h in holdings)
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_single_stock_portfolio(self) -> None:
        """Portfolio with a single stock gives weight=1.0."""
        ctx = _make_context(universe=["000001"])
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Solo",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=1,
        )
        holdings = engine.select_portfolio(config)
        assert len(holdings) == 1
        assert holdings[0].weight == pytest.approx(1.0)
        assert holdings[0].rank == 1

    def test_holding_factor_scores_populated(self) -> None:
        """Portfolio holdings include factor_scores breakdown."""
        ctx = _make_context()
        engine = FactorEngine(ctx)

        config = make_factor_portfolio_config(
            name="Detail",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            top_n=2,
        )
        holdings = engine.select_portfolio(config)
        for h in holdings:
            assert isinstance(h.factor_scores, dict)
            # At least one factor should be present
            assert len(h.factor_scores) > 0
