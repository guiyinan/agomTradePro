"""Typed value conversion helpers for Audit indicator persistence."""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass
class MacroFactCandidate:
    """Typed projection used by the canonical macro-fact selector."""

    indicator_code: str
    reporting_period: date
    value: float
    source: str
    revision_number: int
    published_at: date | None
    fetched_at: datetime
    extra: Mapping[str, object]


def optional_finite_float(value: object) -> float | None:
    """Return a finite float while preserving a legitimate zero."""
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float, Decimal, str))
    ):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def required_finite_float(value: object, *, field_name: str) -> float:
    """Return a finite float or reject corrupted persisted input."""
    numeric = optional_finite_float(value)
    if numeric is None:
        raise ValueError(f"{field_name} must be finite")
    return numeric


def nonnegative_int(value: object, *, field_name: str) -> int:
    """Return a non-negative integer without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def json_mapping(value: object) -> dict[str, object]:
    """Narrow a JSON object to string-keyed metadata."""
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def json_float_mapping(value: object) -> dict[str, float]:
    """Narrow JSON numeric mappings and drop invalid values."""
    return {
        str(key): numeric
        for key, item in json_mapping(value).items()
        if (numeric := optional_finite_float(item)) is not None
    }


def json_object_list(value: object) -> list[dict[str, object]]:
    """Narrow a JSON list to object entries."""
    if not isinstance(value, list):
        return []
    return [json_mapping(item) for item in value if isinstance(item, Mapping)]
