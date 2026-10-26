"""Application adapter for correction-aware daily performance metrics."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from apps.simulated_trading.application.ports import DailyNetValueRecord
from apps.simulated_trading.domain.daily_net_value_metrics import (
    DailyNetValueMetricInput,
    DailyNetValueMetricProjection,
)
from apps.simulated_trading.domain.daily_net_value_metrics import (
    project_daily_net_value_metrics as _project_daily_net_value_metrics,
)
from shared.numeric import safe_float


def _normalized_float(value: object) -> float | None:
    """Convert repository values while keeping booleans outside the numeric domain."""

    if isinstance(value, bool):
        return None
    return safe_float(value)


def project_daily_net_value_metrics(
    records: Sequence[DailyNetValueRecord],
    *,
    initial_capital: Decimal | float | None,
) -> tuple[DailyNetValueMetricProjection, ...]:
    """Normalize repository values, then delegate calculations to the Domain."""

    normalized_records = tuple(
        DailyNetValueMetricInput(
            net_value=_normalized_float(record["net_value"]),
            stored_daily_return=_normalized_float(
                record.get("original_daily_return", record["daily_return"])
            ),
            stored_cumulative_return=_normalized_float(
                record.get("original_cumulative_return", record["cumulative_return"])
            ),
            stored_drawdown=_normalized_float(record.get("original_drawdown", record["drawdown"])),
            correction_coverage_known=record.get("correction_coverage_known") is True,
            correction_overlay_applied=record.get("correction_overlay_applied") is True,
        )
        for record in records
    )
    return _project_daily_net_value_metrics(
        normalized_records,
        initial_capital=_normalized_float(initial_capital),
    )


__all__ = [
    "DailyNetValueMetricInput",
    "DailyNetValueMetricProjection",
    "project_daily_net_value_metrics",
]
