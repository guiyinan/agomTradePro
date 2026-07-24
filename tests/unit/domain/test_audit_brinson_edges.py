"""Brinson decomposition tests for the Audit Domain."""

from datetime import date

import pytest

from apps.audit.domain.brinson_services import calculate_brinson_attribution


def test_brinson_decomposes_excess_return_and_monthly_periods() -> None:
    """Allocation, selection, interaction, and period evidence are reproducible."""
    january = date(2026, 1, 15)
    february = date(2026, 2, 15)
    result = calculate_brinson_attribution(
        portfolio_returns={
            "equity": [(january, 0.10), (february, 0.05)],
            "bond": [(january, 0.02), (february, 0.01)],
        },
        benchmark_returns={
            "equity": [(january, 0.08), (february, 0.04)],
            "bond": [(january, 0.03), (february, 0.02)],
            "cash": [(january, 0.0), (february, 0.0)],
        },
        portfolio_weights={
            "equity": {january: 0.7, february: 0.7},
            "bond": {january: 0.3, february: 0.3},
        },
        benchmark_weights={
            "equity": {january: 0.6, february: 0.6},
            "bond": {january: 0.3, february: 0.3},
            "cash": {january: 0.1, february: 0.1},
        },
        evaluation_period=(date(2026, 1, 1), date(2026, 2, 28)),
    )

    assert result.portfolio_return == pytest.approx(0.057)
    assert result.benchmark_return == pytest.approx(0.0435)
    assert result.excess_return == pytest.approx(0.0135)
    assert result.attribution_sum == pytest.approx(
        result.allocation_effect + result.selection_effect + result.interaction_effect
    )
    assert set(result.sector_breakdown) == {"equity", "bond", "cash"}
    assert len(result.period_breakdown) == 2
    assert result.period_breakdown[0]["start_date"] == date(2026, 1, 1)
    assert result.period_breakdown[1]["end_date"] == date(2026, 2, 28)


def test_brinson_handles_empty_windows_and_crosses_december() -> None:
    """Missing observations become zero and December rolls into a new year."""
    result = calculate_brinson_attribution(
        portfolio_returns={"equity": [(date(2025, 1, 1), 0.5)]},
        benchmark_returns={},
        portfolio_weights={},
        benchmark_weights={},
        evaluation_period=(date(2026, 12, 1), date(2027, 1, 31)),
    )
    assert result.portfolio_return == 0.0
    assert result.benchmark_return == 0.0
    assert len(result.period_breakdown) == 2
    assert result.period_breakdown[0]["end_date"] == date(2026, 12, 31)
    assert result.period_breakdown[1]["start_date"] == date(2027, 1, 1)


def test_single_day_brinson_has_no_nested_periods() -> None:
    """A one-day attribution terminates without recursive period generation."""
    day = date(2026, 7, 24)
    result = calculate_brinson_attribution(
        portfolio_returns={"equity": [(day, 0.01)]},
        benchmark_returns={"equity": [(day, 0.005)]},
        portfolio_weights={"equity": {day: 1.0}},
        benchmark_weights={"equity": {day: 1.0}},
        evaluation_period=(day, day),
    )
    assert result.excess_return == pytest.approx(0.005)
    assert result.period_breakdown == []
