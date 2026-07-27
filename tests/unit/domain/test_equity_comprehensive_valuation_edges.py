"""Comprehensive valuation boundaries for the Equity Domain."""

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from apps.equity.domain.entities import FinancialData, ValuationMetrics
from apps.equity.domain.services_comprehensive_valuation import (
    ComprehensiveValuationAnalyzer,
    ValuationScore,
)


def _financial(
    *,
    revenue_growth: float = 20,
    profit_growth: float = 20,
    roe: float = 15,
    debt_ratio: float = 40,
) -> FinancialData:
    """Build complete financial facts."""
    return FinancialData(
        stock_code="000001.SZ",
        report_date=date(2026, 6, 30),
        revenue=Decimal("1000"),
        net_profit=Decimal("100"),
        revenue_growth=revenue_growth,
        net_profit_growth=profit_growth,
        total_assets=Decimal("2000"),
        total_liabilities=Decimal("800"),
        equity=Decimal("1200"),
        roe=roe,
        roa=8,
        debt_ratio=debt_ratio,
    )


def _valuation(*, pe: float = 15, pb: float = 1.5) -> ValuationMetrics:
    """Build complete point-in-time valuation facts."""
    return ValuationMetrics(
        stock_code="000001.SZ",
        trade_date=date(2026, 7, 24),
        pe=pe,
        pb=pb,
        ps=2,
        total_mv=Decimal("100000000000"),
        circ_mv=Decimal("80000000000"),
        dividend_yield=2,
    )


def test_comprehensive_analysis_returns_all_methods_and_auditable_recommendation() -> None:
    """The public analyzer combines four independent valuation methods."""
    result = ComprehensiveValuationAnalyzer().analyze(
        "000001.SZ",
        _financial(revenue_growth=30, profit_growth=30, roe=20),
        _valuation(pe=10, pb=1),
        historical_pe=[8, 10, 20, 30],
        historical_pb=[0.8, 1.0, 2.0, 3.0],
        industry_avg_pe=20,
        industry_avg_pb=2,
    )
    assert result.stock_code == "000001.SZ"
    assert len(result.scores) == 4
    assert 0 <= result.overall_score <= 100
    assert result.overall_signal in {"strong_buy", "buy", "hold", "sell", "strong_sell"}
    assert result.recommendation
    assert 0.0 <= result.confidence <= 1.0


def test_comprehensive_score_normalizes_active_weights_to_true_hundred_point_scale() -> None:
    """Removing the unavailable DCF method must not compress the theoretical score to 85."""

    result = ComprehensiveValuationAnalyzer().analyze(
        "000001.SZ",
        _financial(revenue_growth=30, profit_growth=30, roe=20),
        _valuation(pe=4, pb=0.4),
        historical_pe=[10, 20, 30],
        historical_pb=[1, 2, 3],
        industry_avg_pe=20,
        industry_avg_pb=2,
    )

    assert result.overall_score == pytest.approx(100.0)
    assert result.overall_signal == "strong_buy"


def test_comprehensive_analysis_rejects_cross_stock_fact_mixing() -> None:
    """Financial and valuation facts for another stock cannot enter one result."""

    with pytest.raises(ValueError, match="must match stock_code"):
        ComprehensiveValuationAnalyzer().analyze(
            "000001.SZ",
            replace(_financial(), stock_code="000002.SZ"),
            _valuation(),
            historical_pe=[10],
            historical_pb=[1],
        )


@pytest.mark.parametrize(
    ("financial", "valuation", "kwargs", "field_name"),
    [
        (_financial(), _valuation(pe=float("nan")), {}, "valuation.pe"),
        (replace(_financial(), roe=float("inf")), _valuation(), {}, "financial.roe"),
        (_financial(), _valuation(), {"industry_avg_pb": float("-inf")}, "industry_avg_pb"),
        (_financial(), _valuation(), {"risk_free_rate": float("nan")}, "risk_free_rate"),
    ],
)
def test_comprehensive_analysis_rejects_non_finite_inputs(
    financial: FinancialData,
    valuation: ValuationMetrics,
    kwargs: dict[str, float],
    field_name: str,
) -> None:
    """NaN and infinity fail closed instead of contaminating scores and signals."""

    with pytest.raises(ValueError, match=field_name):
        ComprehensiveValuationAnalyzer().analyze(
            "000001.SZ",
            financial,
            valuation,
            historical_pe=[10],
            historical_pb=[1],
            **kwargs,
        )


def test_comprehensive_analysis_filters_non_finite_history_observations() -> None:
    """Bad historical rows are excluded while valid point-in-time observations remain usable."""

    analyzer = ComprehensiveValuationAnalyzer()
    result = analyzer.analyze(
        "000001.SZ",
        _financial(),
        _valuation(),
        historical_pe=[float("nan"), float("inf"), -1, 10, 20],
        historical_pb=[float("nan"), float("-inf"), 0, 1, 2],
    )
    expected = analyzer._analyze_pe_pb_percentile(_valuation(), [10, 20], [1, 2])

    assert result.scores[0].details == expected.details
    with pytest.raises(FrozenInstanceError):
        result.overall_score = 0


@pytest.mark.parametrize(
    ("ratio", "score", "signal"),
    [
        (0.6, 100, "undervalued"),
        (0.8, 80, "fair"),
        (0.9, 60, "fair"),
        (1.1, 40, "fair"),
        (1.3, 20, "overvalued"),
    ],
)
def test_industry_relative_valuation_bands(ratio: float, score: int, signal: str) -> None:
    """Relative PE/PB bands keep their exact score and signal semantics."""
    result = ComprehensiveValuationAnalyzer()._analyze_vs_industry(
        _valuation(pe=20 * ratio, pb=2 * ratio),
        20,
        2,
    )
    assert result.score == score
    assert result.signal == signal


def test_industry_relative_valuation_handles_invalid_benchmarks() -> None:
    """Non-positive industry averages use neutral ratios rather than divide by zero."""
    result = ComprehensiveValuationAnalyzer()._analyze_vs_industry(
        _valuation(),
        0,
        0,
    )
    assert result.details["avg_ratio"] == 1.0
    assert result.score == 60


def test_industry_relative_valuation_treats_non_positive_current_multiples_as_neutral() -> None:
    """Loss-making or negative-equity multiples cannot be rewarded as deeply undervalued."""

    result = ComprehensiveValuationAnalyzer()._analyze_vs_industry(
        _valuation(pe=-10, pb=-1),
        20,
        2,
    )

    assert result.details["avg_ratio"] == 1.0
    assert result.score == 60
    assert result.signal == "fair"


@pytest.mark.parametrize(
    ("pe", "growth", "score", "signal"),
    [
        (10, 0, 50, "fair"),
        (4, 10, 100, "undervalued"),
        (6, 10, 80, "undervalued"),
        (9, 10, 60, "fair"),
        (12, 10, 40, "overvalued"),
        (20, 10, 20, "overvalued"),
    ],
)
def test_peg_bands_and_invalid_growth(pe: float, growth: float, score: int, signal: str) -> None:
    """PEG rejects non-growth cases and maps each threshold band."""
    result = ComprehensiveValuationAnalyzer()._analyze_peg(
        _financial(revenue_growth=growth, profit_growth=growth),
        _valuation(pe=pe),
    )
    assert result.score == score
    assert result.signal == signal


@pytest.mark.parametrize(
    ("financial", "score", "signal"),
    [
        (_financial(roe=20, revenue_growth=30, profit_growth=30), 100, "undervalued"),
        (_financial(roe=15, revenue_growth=20, profit_growth=20), 100, "undervalued"),
        (_financial(roe=10, revenue_growth=10, profit_growth=10), 80, "undervalued"),
        (_financial(roe=9, revenue_growth=9, profit_growth=9), 50, "overvalued"),
        (
            _financial(
                roe=9,
                revenue_growth=9,
                profit_growth=9,
                debt_ratio=60,
            ),
            40,
            "overvalued",
        ),
        (
            _financial(
                roe=9,
                revenue_growth=9,
                profit_growth=9,
                debt_ratio=80,
            ),
            30,
            "overvalued",
        ),
    ],
)
def test_quality_score_rewards_growth_and_penalizes_leverage(
    financial: FinancialData, score: int, signal: str
) -> None:
    """Quality scoring covers ROE, growth, and debt branches."""
    result = ComprehensiveValuationAnalyzer()._analyze_quality(financial)
    assert result.score == score
    assert result.signal == signal


@pytest.mark.parametrize(
    ("score", "signal"),
    [
        (85, "strong_buy"),
        (70, "buy"),
        (40, "hold"),
        (25, "sell"),
        (24, "strong_sell"),
    ],
)
def test_overall_signal_boundaries(score: float, signal: str) -> None:
    """Recommendation signal boundaries are inclusive at their floors."""
    assert ComprehensiveValuationAnalyzer()._determine_signal(score) == signal


def test_recommendation_and_confidence_cover_consensus_and_unknown_signal() -> None:
    """Recommendation text and confidence derive only from method consensus."""
    analyzer = ComprehensiveValuationAnalyzer()
    undervalued = [
        ValuationScore("a", 90, "undervalued", {}),
        ValuationScore("b", 80, "undervalued", {}),
        ValuationScore("c", 60, "fair", {}),
    ]
    overvalued = [
        ValuationScore("a", 10, "overvalued", {}),
        ValuationScore("b", 20, "overvalued", {}),
    ]
    assert "2种方法" in analyzer._generate_recommendation("strong_buy", undervalued)
    assert "买入" in analyzer._generate_recommendation("buy", undervalued)
    assert "持有" in analyzer._generate_recommendation("hold", undervalued)
    assert "减仓" in analyzer._generate_recommendation("sell", overvalued)
    assert "2种方法" in analyzer._generate_recommendation("strong_sell", overvalued)
    assert analyzer._generate_recommendation("unknown", undervalued) == "暂无明确建议"
    assert analyzer._calculate_confidence(overvalued) > analyzer._calculate_confidence(undervalued)
    assert analyzer._calculate_confidence([]) == 0.0
