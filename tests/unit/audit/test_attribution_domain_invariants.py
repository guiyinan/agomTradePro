"""Truthfulness invariants for Audit attribution domain calculations."""

from dataclasses import dataclass
from datetime import date

import pytest

from apps.audit.domain.attribution_services import (
    AttributionAnalyzer,
    _build_regime_periods,
    _calculate_period_performances,
    _calculate_total_transaction_cost,
)
from apps.audit.domain.entities import RegimePeriod
from apps.backtest.domain.entities import Trade


@dataclass(frozen=True)
class BacktestResultStub:
    """Minimal immutable result accepted by the attribution analyzer."""

    equity_curve: list[tuple[date, float]]
    trades: list[Trade]
    total_return: float = 0.0


def test_regime_accuracy_aligns_observations_by_date() -> None:
    """Reordered inputs must not turn correct dated predictions into errors."""

    predicted = [
        {"date": date(2024, 1, 1), "regime": "RECOVERY"},
        {"date": date(2024, 2, 1), "regime": "OVERHEAT"},
    ]
    actual = [
        {"date": date(2024, 2, 1), "regime": "Overheat"},
        {"date": date(2024, 1, 1), "regime": "Recovery"},
    ]

    result = AttributionAnalyzer().analyze_regime_accuracy(predicted, actual)

    assert result["total_periods"] == 2
    assert result["correct_predictions"] == 2
    assert result["accuracy"] == 1.0
    assert result["regime_confusion_matrix"]["Recovery"]["Recovery"] == 1
    assert result["regime_confusion_matrix"]["Overheat"]["Overheat"] == 1


def test_regime_periods_sort_and_drop_invalid_observations() -> None:
    """Invalid or non-finite observations must not enter attribution periods."""

    periods = _build_regime_periods(
        [
            {"date": date(2024, 2, 1), "regime": "OVERHEAT", "confidence": 0.8},
            {"date": "invalid", "regime": "RECOVERY", "confidence": 0.9},
            {"date": date(2024, 1, 1), "regime": "RECOVERY", "confidence": 0.7},
            {"date": date(2024, 3, 1), "regime": " ", "confidence": 0.5},
            {"date": date(2024, 4, 1), "regime": "DEFLATION", "confidence": float("nan")},
        ]
    )

    assert [period.regime for period in periods] == ["RECOVERY", "OVERHEAT"]
    assert periods[0].start_date == date(2024, 1, 1)


@pytest.mark.parametrize(
    ("equity_curve", "benchmark_returns"),
    [
        ([(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 101.0)], []),
        ([(date(2024, 1, 1), 0.0), (date(2024, 1, 2), 101.0)], [0.0]),
        ([(date(2024, 1, 1), 100.0), (date(2024, 1, 2), float("nan"))], [0.0]),
        ([(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 101.0)], [float("inf")]),
    ],
)
def test_information_ratio_rejects_incomplete_or_invalid_series(
    equity_curve: list[tuple[date, float]],
    benchmark_returns: list[float],
) -> None:
    """Information ratio must not fabricate benchmark data or divide by zero."""

    result = AttributionAnalyzer().calculate_information_ratio(
        BacktestResultStub(equity_curve=equity_curve, trades=[]),
        benchmark_returns,
    )

    assert result is None


def test_period_performance_skips_zero_start_value_and_non_finite_returns() -> None:
    """A zero portfolio base is invalid and asset NaN values are never averaged."""

    period = RegimePeriod(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        regime="RECOVERY",
    )
    assert (
        _calculate_period_performances(
            [period],
            [(date(2024, 1, 1), 0.0), (date(2024, 1, 2), 100.0)],
            {},
        )
        == []
    )

    performances = _calculate_period_performances(
        [period],
        [(date(2024, 1, 1), 100.0), (date(2024, 1, 2), 101.0)],
        {"equity": [(date(2024, 1, 1), float("nan"))]},
    )
    assert performances[0].asset_returns["equity"] == 0.0


def test_transaction_cost_rejects_non_finite_total() -> None:
    """Corrupted transaction costs must fail rather than publish a NaN total."""

    trade = Trade(
        trade_date=date(2024, 1, 1),
        asset_class="equity",
        action="buy",
        shares=1.0,
        price=1.0,
        notional=1.0,
        cost=float("nan"),
    )

    with pytest.raises(ValueError, match="finite"):
        _calculate_total_transaction_cost([trade])
