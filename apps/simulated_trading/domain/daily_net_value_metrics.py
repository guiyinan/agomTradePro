"""Pure correction-aware performance metrics for daily net-value rows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class DailyNetValueMetricInput:
    """Normalized values needed to calculate one daily performance row."""

    net_value: float | None
    stored_daily_return: float | None
    stored_cumulative_return: float | None
    stored_drawdown: float | None
    correction_coverage_known: bool
    correction_overlay_applied: bool


@dataclass(frozen=True, slots=True)
class DailyNetValueMetricProjection:
    """Stored and effective return metrics for one immutable snapshot row."""

    original_daily_return: float | None
    original_cumulative_return: float | None
    original_drawdown: float | None
    daily_return: float | None
    cumulative_return: float | None
    drawdown: float | None
    metrics_known: bool
    reason_code: str | None


def _finite_float(value: float | None) -> float | None:
    """Normalize a typed number and reject booleans, invalid, and non-finite values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return normalized if isfinite(normalized) else None


def _percent_change(current: float, baseline: float) -> float | None:
    """Calculate a percentage change only when the result is representable."""

    if baseline <= 0.0:
        return None
    difference = current - baseline
    if not isfinite(difference):
        return None
    ratio = difference / baseline
    if not isfinite(ratio):
        return None
    result = ratio * 100.0
    return result if isfinite(result) else None


def _drawdown(current: float, peak: float) -> float | None:
    """Calculate nonnegative drawdown from a positive peak."""

    if peak <= 0.0:
        return None
    difference = peak - current
    if not isfinite(difference):
        return None
    ratio = difference / peak
    if not isfinite(ratio):
        return None
    result = ratio * 100.0
    if not isfinite(result):
        return None
    return max(0.0, result)


def project_daily_net_value_metrics(
    records: Sequence[DailyNetValueMetricInput],
    *,
    initial_capital: float | None,
) -> tuple[DailyNetValueMetricProjection, ...]:
    """Project effective metrics without mutating stored daily observations.

    Stored metrics are retained until the first correction overlay. From that
    row onward, metrics are recalculated from the complete ordered net-value
    history. Unknown coverage or an invalid net value blocks all dependent
    rows with a stable reason code.
    """

    if not records:
        return ()

    start_value = _finite_float(initial_capital)
    capital_known = start_value is not None and start_value > 0.0
    projection_started = False
    blocked_reason: str | None = None
    previous_value: float | None = None
    peak_value: float | None = None
    result: list[DailyNetValueMetricProjection] = []

    for record in records:
        original_daily = _finite_float(record.stored_daily_return)
        original_cumulative = _finite_float(record.stored_cumulative_return)
        original_drawdown = _finite_float(record.stored_drawdown)
        net_value = _finite_float(record.net_value)

        if record.correction_overlay_applied is True:
            projection_started = True
        if record.correction_coverage_known is not True:
            blocked_reason = "FEE_CORRECTION_COVERAGE_UNKNOWN"
        elif blocked_reason is None and net_value is None:
            blocked_reason = "DAILY_NET_VALUE_INVALID"

        daily_return = original_daily
        cumulative_return = original_cumulative
        drawdown = original_drawdown
        reason_code: str | None = blocked_reason

        if blocked_reason is not None:
            daily_return = None
            cumulative_return = None
            drawdown = None
        elif projection_started and net_value is not None:
            if previous_value is None or previous_value <= 0.0:
                daily_return = None
                reason_code = "DAILY_RETURN_BASELINE_UNAVAILABLE"
            else:
                daily_return = _percent_change(net_value, previous_value)
                if daily_return is None:
                    reason_code = "DAILY_RETURN_UNREPRESENTABLE"

            if capital_known and start_value is not None:
                cumulative_return = _percent_change(net_value, start_value)
                if cumulative_return is None:
                    reason_code = reason_code or "CUMULATIVE_RETURN_UNREPRESENTABLE"
            else:
                cumulative_return = None
                reason_code = reason_code or "INITIAL_CAPITAL_UNKNOWN"

            peak_value = net_value if peak_value is None else max(peak_value, net_value)
            drawdown = _drawdown(net_value, peak_value)
            if drawdown is None:
                reason_code = reason_code or "DAILY_NET_VALUE_PEAK_INVALID"
        elif original_daily is None or original_cumulative is None or original_drawdown is None:
            reason_code = "STORED_PERFORMANCE_VALUE_INVALID"

        metrics_known = (
            daily_return is not None
            and cumulative_return is not None
            and drawdown is not None
            and blocked_reason is None
        )
        result.append(
            DailyNetValueMetricProjection(
                original_daily_return=original_daily,
                original_cumulative_return=original_cumulative,
                original_drawdown=original_drawdown,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                drawdown=drawdown,
                metrics_known=metrics_known,
                reason_code=reason_code,
            )
        )

        if net_value is not None and blocked_reason is None:
            previous_value = net_value
            if peak_value is None or net_value > peak_value:
                peak_value = net_value

    return tuple(result)


__all__ = [
    "DailyNetValueMetricInput",
    "DailyNetValueMetricProjection",
    "project_daily_net_value_metrics",
]
