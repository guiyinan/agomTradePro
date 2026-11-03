"""Derive a fail-closed deadline from actual policy and source bounds."""

from __future__ import annotations

from datetime import UTC, datetime


def earliest_portfolio_risk_acceptance_deadline(
    *,
    as_of: datetime,
    policy_deadlines: tuple[datetime, ...],
    source_valid_until: datetime | None = None,
) -> datetime | None:
    """Return the earliest future bound, without inventing a TTL or source expiry.

    Callers must provide only bounds derived from the active policy or an actual
    source-origin ``valid_until``. An empty set, malformed clock or already
    expired minimum returns ``None`` so consumers keep the existing strict gate.
    """

    if type(as_of) is not datetime or not _is_aware(as_of):
        return None
    if type(policy_deadlines) is not tuple:
        return None
    if any(type(value) is not datetime or not _is_aware(value) for value in policy_deadlines):
        return None
    if source_valid_until is not None and (
        type(source_valid_until) is not datetime or not _is_aware(source_valid_until)
    ):
        return None

    try:
        candidates = [value.astimezone(UTC) for value in policy_deadlines]
        if source_valid_until is not None:
            candidates.append(source_valid_until.astimezone(UTC))
        if not candidates:
            return None
        cutoff = as_of.astimezone(UTC)
        earliest = min(candidates)
        return earliest if earliest > cutoff else None
    except (ArithmeticError, OverflowError, TypeError, ValueError):
        return None


def _is_aware(value: datetime) -> bool:
    """Return whether a datetime has a usable UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = ["earliest_portfolio_risk_acceptance_deadline"]
