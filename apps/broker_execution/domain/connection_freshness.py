"""Pure source/receipt clock rules for Broker Agent current health."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

HEARTBEAT_FRESHNESS = timedelta(seconds=90)


def heartbeat_times_are_fresh(
    *,
    source_observed_at: datetime | None,
    received_at: datetime | None,
    evaluated_at: datetime,
) -> bool:
    """Return true only when both aware clocks are current and correctly ordered."""

    if evaluated_at.tzinfo is None:
        return False
    if (
        source_observed_at is None
        or source_observed_at.tzinfo is None
        or received_at is None
        or received_at.tzinfo is None
    ):
        return False
    source = source_observed_at.astimezone(UTC)
    received = received_at.astimezone(UTC)
    evaluated = evaluated_at.astimezone(UTC)
    return evaluated - HEARTBEAT_FRESHNESS <= source <= received <= evaluated
