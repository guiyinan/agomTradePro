"""Validation helpers shared by market-breadth repository owners."""

from __future__ import annotations

from datetime import date


def validated_code(value: str, *, field_name: str) -> str:
    """Validate a bounded lookup code before building an ORM query."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > 64:
        raise ValueError(f"{field_name} must contain 1 to 64 characters.")
    return normalized


def validated_limit(limit: int) -> int:
    """Reject unbounded, boolean, and non-positive query limits."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000.")
    return limit


def validate_date_range(start: date | None, end: date | None) -> None:
    """Reject inverted date ranges before querying storage."""

    if start is not None and end is not None and start > end:
        raise ValueError("start cannot be after end.")


__all__ = ["validate_date_range", "validated_code", "validated_limit"]
