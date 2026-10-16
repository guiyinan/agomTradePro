"""Execution quote source-time checks shared by staging and activation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from apps.data_center.domain.contracts import MAX_CATALOG_TTL_SECONDS


def validate_execution_quote_member_freshness(
    observed_at_values: Sequence[datetime | None],
    *,
    as_of: datetime,
    execution_freshness_seconds: int,
) -> None:
    """Require every source observation to be known and within the execution TTL."""

    if (
        type(execution_freshness_seconds) is not int
        or execution_freshness_seconds <= 0
        or execution_freshness_seconds > MAX_CATALOG_TTL_SECONDS
    ):
        raise ValueError("execution quote freshness TTL is invalid")
    as_of_utc = _to_utc(as_of, "execution freshness cutoff")
    if not observed_at_values:
        raise ValueError("execution quote observations are required")
    for observed_at in observed_at_values:
        if observed_at is None:
            raise ValueError("execution quote observation time is missing")
        observed_at_utc = _to_utc(observed_at, "execution quote observation")
        if observed_at_utc > as_of_utc:
            raise ValueError("execution quote observation follows the freshness cutoff")
        try:
            deadline = observed_at_utc + timedelta(seconds=execution_freshness_seconds)
        except (OverflowError, ValueError):
            raise ValueError("execution quote freshness deadline overflows") from None
        if as_of_utc >= deadline:
            raise ValueError("execution quote observation has expired its freshness window")


def _to_utc(value: datetime, field_name: str) -> datetime:
    """Require one aware datetime and normalize it before comparing instants."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")
        return value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f"{field_name} is not a valid timezone-aware instant") from None


__all__ = ["validate_execution_quote_member_freshness"]
