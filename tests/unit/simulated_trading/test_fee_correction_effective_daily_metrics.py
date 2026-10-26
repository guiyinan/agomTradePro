"""Pure contracts for original and correction-aware daily performance values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from apps.simulated_trading.application.daily_net_value_metrics import (
    project_daily_net_value_metrics,
)


def _record(
    day: int,
    net_value: str,
    *,
    correction_coverage_known: bool = True,
    correction_overlay_applied: bool = False,
    daily_return: float = 0.0,
    cumulative_return: float = 0.0,
    drawdown: float = 0.0,
) -> dict[str, object]:
    return {
        "record_date": date(2026, 10, day),
        "net_value": Decimal(net_value),
        "correction_coverage_known": correction_coverage_known,
        "correction_overlay_applied": correction_overlay_applied,
        "daily_return": daily_return,
        "cumulative_return": cumulative_return,
        "drawdown": drawdown,
    }


def test_overlay_recomputes_effective_metrics_and_preserves_original_values() -> None:
    rows = [
        _record(1, "100.00", daily_return=0.0, cumulative_return=0.0, drawdown=0.0),
        _record(
            2,
            "80.00",
            correction_overlay_applied=True,
            daily_return=-10.0,
            cumulative_return=-10.0,
            drawdown=10.0,
        ),
        _record(3, "90.00", daily_return=12.5, cumulative_return=-10.0, drawdown=0.0),
    ]

    projected = project_daily_net_value_metrics(rows, initial_capital=Decimal("100.00"))

    assert [row.daily_return for row in projected] == [0.0, -20.0, 12.5]
    assert [row.cumulative_return for row in projected] == [0.0, -20.0, -10.0]
    assert [row.drawdown for row in projected] == [0.0, 20.0, 10.0]
    assert projected[1].original_daily_return == -10.0
    assert projected[1].original_cumulative_return == -10.0
    assert projected[1].original_drawdown == 10.0
    assert all(row.metrics_known is True for row in projected)
    assert all(row.reason_code is None for row in projected)


def test_incomplete_correction_coverage_does_not_reuse_stale_metrics() -> None:
    rows = [
        _record(1, "100.00", daily_return=0.0, cumulative_return=0.0, drawdown=0.0),
        _record(
            2,
            "80.00",
            correction_coverage_known=False,
            daily_return=-20.0,
            cumulative_return=-20.0,
            drawdown=20.0,
        ),
        _record(3, "90.00", daily_return=12.5, cumulative_return=-10.0, drawdown=10.0),
    ]

    projected = project_daily_net_value_metrics(rows, initial_capital=Decimal("100.00"))

    assert projected[0].metrics_known is True
    assert projected[0].daily_return == 0.0
    assert projected[1].daily_return is None
    assert projected[1].cumulative_return is None
    assert projected[1].drawdown is None
    assert projected[2].daily_return is None
    assert projected[2].cumulative_return is None
    assert projected[2].drawdown is None
    assert projected[1].reason_code == "FEE_CORRECTION_COVERAGE_UNKNOWN"
    assert projected[2].reason_code == "FEE_CORRECTION_COVERAGE_UNKNOWN"
    assert projected[1].original_daily_return == -20.0


def test_unadjusted_history_keeps_the_persisted_metric_contract() -> None:
    rows = [
        _record(1, "101.00", daily_return=1.0, cumulative_return=1.0, drawdown=0.0),
        _record(2, "102.00", daily_return=0.99, cumulative_return=2.0, drawdown=0.0),
    ]

    projected = project_daily_net_value_metrics(rows, initial_capital=Decimal("100.00"))

    assert projected[0].daily_return == 1.0
    assert projected[1].daily_return == 0.99
    assert projected[1].cumulative_return == 2.0
    assert all(row.metrics_known is True for row in projected)


def test_corrected_new_high_has_zero_drawdown_and_updates_future_peak() -> None:
    rows = [
        _record(1, "100.00", daily_return=0.0, cumulative_return=0.0, drawdown=0.0),
        _record(
            2,
            "120.00",
            correction_overlay_applied=True,
            daily_return=20.0,
            cumulative_return=20.0,
            drawdown=0.0,
        ),
        _record(3, "110.00", daily_return=-8.33, cumulative_return=10.0, drawdown=8.33),
    ]

    projected = project_daily_net_value_metrics(rows, initial_capital=Decimal("100.00"))

    assert projected[1].drawdown == 0.0
    assert projected[2].drawdown == pytest.approx(100.0 / 12.0)
    assert projected[1].metrics_known is True
    assert projected[2].metrics_known is True


def test_application_adapter_is_independent_of_ambient_decimal_context() -> None:
    rows = [
        _record(1, "100.00"),
        _record(2, "120.00", correction_overlay_applied=True),
    ]

    with localcontext() as context:
        context.prec = 2
        context.Emax = 4
        context.Emin = -4
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        projected = project_daily_net_value_metrics(
            rows,
            initial_capital=Decimal("100.00"),
        )

    assert projected[1].daily_return == 20.0
    assert projected[1].cumulative_return == 20.0
    assert projected[1].drawdown == 0.0


def test_application_adapter_rejects_boolean_net_value() -> None:
    rows = [
        _record(1, "100.00"),
        _record(2, "110.00", correction_overlay_applied=True),
    ]
    rows[1]["net_value"] = True

    projected = project_daily_net_value_metrics(rows, initial_capital=Decimal("100.00"))

    assert projected[1].daily_return is None
    assert projected[1].cumulative_return is None
    assert projected[1].reason_code == "DAILY_NET_VALUE_INVALID"


@pytest.mark.parametrize("metric_field", ["daily_return", "cumulative_return", "drawdown"])
def test_application_adapter_rejects_boolean_stored_metrics(metric_field: str) -> None:
    row = _record(1, "100.00")
    row[metric_field] = True

    projected = project_daily_net_value_metrics([row], initial_capital=Decimal("100.00"))[0]

    assert projected.metrics_known is False
    assert projected.reason_code == "STORED_PERFORMANCE_VALUE_INVALID"
    assert True not in (
        projected.original_daily_return,
        projected.original_cumulative_return,
        projected.original_drawdown,
    )


def test_application_adapter_rejects_boolean_initial_capital() -> None:
    rows = [
        _record(1, "100.00"),
        _record(2, "110.00", correction_overlay_applied=True),
    ]

    projected = project_daily_net_value_metrics(rows, initial_capital=True)[1]

    assert projected.cumulative_return is None
    assert projected.reason_code == "INITIAL_CAPITAL_UNKNOWN"
