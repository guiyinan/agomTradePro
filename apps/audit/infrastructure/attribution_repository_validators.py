"""Validation and serialization helpers for attribution persistence."""

import math
import re
from datetime import date, datetime

from apps.audit.domain.interfaces import AttributionReportRecord

from .models import AttributionReport

ATTRIBUTION_METHODS = frozenset({"heuristic", "brinson"})
LOSS_SOURCES = frozenset(
    {
        "REGIME_ERROR",
        "TIMING_ERROR",
        "ASSET_SELECTION_ERROR",
        "EXECUTION_ERROR",
        "TRANSACTION_COST",
        "POLICY_MISJUDGMENT",
        "EXTERNAL_SHOCK",
    }
)
EXPERIENCE_PRIORITIES = frozenset({"HIGH", "MEDIUM", "LOW"})
_REGIME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def serialize_valid_reports(
    reports: object,
) -> list[AttributionReportRecord]:
    """Serialize an iterable of ORM reports while isolating corrupted rows."""
    payloads: list[AttributionReportRecord] = []
    if not hasattr(reports, "__iter__"):
        return payloads
    for report in reports:
        if not isinstance(report, AttributionReport):
            continue
        payload = serialize_report(report)
        if payload is not None:
            payloads.append(payload)
    return payloads


def serialize_report(report: AttributionReport) -> AttributionReportRecord | None:
    """Serialize one report, rejecting corrupted persisted numeric evidence."""
    regime_timing = persisted_finite_float(report.regime_timing_pnl)
    asset_selection = persisted_finite_float(report.asset_selection_pnl)
    interaction = persisted_finite_float(report.interaction_pnl)
    total = persisted_finite_float(report.total_pnl)
    accuracy = persisted_finite_float(report.regime_accuracy)
    if (
        regime_timing is None
        or asset_selection is None
        or interaction is None
        or total is None
        or accuracy is None
        or not 0.0 <= accuracy <= 1.0
        or report.period_start > report.period_end
        or report.attribution_method not in ATTRIBUTION_METHODS
        or not is_regime_token(report.regime_predicted, maximum=20)
        or (
            report.regime_actual is not None
            and not is_regime_token(report.regime_actual, maximum=64)
        )
    ):
        return None
    return {
        "id": report.id,
        "backtest_id": report.backtest_id,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "attribution_method": report.attribution_method,
        "attribution_method_display": report.get_attribution_method_display(),
        "regime_timing_pnl": regime_timing,
        "asset_selection_pnl": asset_selection,
        "interaction_pnl": interaction,
        "total_pnl": total,
        "regime_accuracy": accuracy,
        "regime_predicted": report.regime_predicted,
        "regime_actual": report.regime_actual,
        "created_at": report.created_at.isoformat(),
    }


def validated_date_range(start: object, end: object) -> tuple[date, date]:
    """Return an ordered pair of plain dates."""
    normalized_start = plain_date(start, label="period_start")
    normalized_end = plain_date(end, label="period_end")
    if normalized_start > normalized_end:
        raise ValueError("period_start must not be after period_end")
    return normalized_start, normalized_end


def plain_date(value: object, *, label: str) -> date:
    """Return a date while rejecting datetime and dynamic impostors."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{label} must be a date")
    return value


def positive_id(value: object, *, label: str) -> int:
    """Return one strict positive integer ID."""
    return bounded_int(value, label=label, minimum=1, maximum=2**63 - 1)


def optional_positive_id(value: object) -> int | None:
    """Return a positive integer or None for invalid lookup input."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    """Return a strict bounded integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def finite_float(value: object, *, label: str) -> float:
    """Return a finite real number without accepting bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    return normalized


def persisted_finite_float(value: object) -> float | None:
    """Return a finite persisted number or None for corrupted evidence."""
    try:
        return finite_float(value, label="persisted_value")
    except ValueError:
        return None


def unit_interval(value: object, *, label: str) -> float:
    """Return a finite number in the closed unit interval."""
    normalized = finite_float(value, label=label)
    if not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return normalized


def choice(value: object, *, choices: frozenset[str], label: str) -> str:
    """Return one normalized governed choice."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if normalized not in choices:
        raise ValueError(f"{label} is not supported")
    return normalized


def regime_token(value: object, *, label: str, maximum: int) -> str:
    """Return a bounded regime/audit status token."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not is_regime_token(normalized, maximum=maximum):
        raise ValueError(f"{label} has an invalid format")
    return normalized


def is_regime_token(value: object, *, maximum: int) -> bool:
    """Return whether a persisted regime token is structurally safe."""
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and _REGIME_PATTERN.fullmatch(value) is not None
    )


def bounded_text(
    value: object,
    *,
    label: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    """Return bounded text without NUL characters."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if (not allow_empty and not normalized) or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{label} exceeds the supported text boundary")
    return normalized


def saved_id(value: object, *, label: str) -> int:
    """Return the positive ID assigned by Django after insertion."""
    return positive_id(value, label=label)
