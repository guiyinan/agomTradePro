"""Validation and serialization helpers for Audit validation summaries."""

import math
import re
from datetime import date, datetime
from typing import TypeAlias

from .models import ValidationSummaryModel

ValidationSummaryPayload: TypeAlias = dict[str, object]

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
VALIDATION_STATUSES = frozenset({"pending", "in_progress", "completed", "failed"})
MAX_RECENT_VALIDATIONS = 100


def serialize_full_summary(
    summary: ValidationSummaryModel,
    *,
    include_id: bool,
) -> ValidationSummaryPayload:
    """Serialize a full summary without turning legitimate zero scores into null."""
    payload: ValidationSummaryPayload = {
        "validation_run_id": summary.validation_run_id,
        "run_date": summary.run_date.isoformat(),
        "evaluation_period_start": summary.evaluation_period_start.isoformat(),
        "evaluation_period_end": summary.evaluation_period_end.isoformat(),
        "total_indicators": summary.total_indicators,
        "approved_indicators": summary.approved_indicators,
        "rejected_indicators": summary.rejected_indicators,
        "pending_indicators": summary.pending_indicators,
        "avg_f1_score": persisted_optional_score(summary.avg_f1_score),
        "avg_stability_score": persisted_optional_score(summary.avg_stability_score),
        "overall_recommendation": summary.overall_recommendation,
        "status": summary.status,
        "is_shadow_mode": summary.is_shadow_mode,
        "error_message": summary.error_message,
    }
    if include_id:
        payload["id"] = summary.id
    return payload


def serialize_recent_summary(summary: ValidationSummaryModel) -> ValidationSummaryPayload:
    """Serialize the bounded projection used by recent-validation lists."""
    return {
        "validation_run_id": summary.validation_run_id,
        "run_date": summary.run_date.isoformat(),
        "evaluation_period_start": summary.evaluation_period_start.isoformat(),
        "evaluation_period_end": summary.evaluation_period_end.isoformat(),
        "total_indicators": summary.total_indicators,
        "approved_indicators": summary.approved_indicators,
        "rejected_indicators": summary.rejected_indicators,
        "pending_indicators": summary.pending_indicators,
        "avg_f1_score": persisted_optional_score(summary.avg_f1_score),
        "avg_stability_score": persisted_optional_score(summary.avg_stability_score),
        "overall_recommendation": summary.overall_recommendation,
        "status": summary.status,
        "is_shadow_mode": summary.is_shadow_mode,
    }


def normalize_run_id(value: object) -> str | None:
    """Return a canonical run identifier or None for invalid lookup input."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if RUN_ID_PATTERN.fullmatch(normalized) is not None else None


def require_run_id(value: object) -> str:
    """Return a canonical run identifier or reject invalid persistence input."""
    normalized = normalize_run_id(value)
    if normalized is None:
        raise ValueError("validation_run_id has an invalid format")
    return normalized


def validated_date_range(start: object, end: object) -> tuple[date, date]:
    """Return a plain-date range with start not after end."""
    normalized_start = require_plain_date(start, label="evaluation_period_start")
    normalized_end = require_plain_date(end, label="evaluation_period_end")
    if normalized_start > normalized_end:
        raise ValueError("evaluation_period_start must not be after evaluation_period_end")
    if (normalized_end - normalized_start).days > 3_660:
        raise ValueError("evaluation period must not exceed 3660 days")
    return normalized_start, normalized_end


def require_plain_date(value: object, *, label: str) -> date:
    """Return a date while rejecting datetime and dynamic impostors."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"{label} must be a date")
    return value


def validated_counts(
    *,
    total: object,
    approved: object,
    rejected: object,
    pending: object,
    require_complete: bool,
) -> tuple[int, int, int, int]:
    """Validate nonnegative counts and their reconciliation to the total."""
    normalized = (
        bounded_int(total, label="total_indicators", minimum=0, maximum=2**31 - 1),
        bounded_int(approved, label="approved_indicators", minimum=0, maximum=2**31 - 1),
        bounded_int(rejected, label="rejected_indicators", minimum=0, maximum=2**31 - 1),
        bounded_int(pending, label="pending_indicators", minimum=0, maximum=2**31 - 1),
    )
    classified = sum(normalized[1:])
    if classified > normalized[0]:
        raise ValueError("indicator status counts exceed total_indicators")
    if require_complete and classified != normalized[0]:
        raise ValueError("completed validation counts must equal total_indicators")
    return normalized


def bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    """Return a strict bounded integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def optional_positive_id(value: object) -> int | None:
    """Return a positive integer ID or None for invalid lookup input."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def optional_score(value: object, *, label: str) -> float | None:
    """Return an optional finite score in the closed unit interval."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(f"{label} must be finite and between 0 and 1")
    return normalized


def persisted_optional_score(value: object) -> float | None:
    """Return a safe persisted score without publishing NaN or infinity."""
    try:
        return optional_score(value, label="persisted_score")
    except ValueError:
        return None


def validation_status(value: object) -> str:
    """Return one supported validation lifecycle status."""
    if not isinstance(value, str):
        raise ValueError("status must be a string")
    normalized = value.strip().lower()
    if normalized not in VALIDATION_STATUSES:
        raise ValueError("status is not supported")
    return normalized


def strict_bool(value: object, *, label: str) -> bool:
    """Return a real boolean without accepting truthy substitutes."""
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def bounded_text(value: object, *, label: str, maximum: int) -> str:
    """Return bounded text suitable for an Audit summary record."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} exceeds the supported text boundary")
    return value
