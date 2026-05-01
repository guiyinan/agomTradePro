"""Application-facing helpers for events admin and interface entry points."""

from __future__ import annotations

from apps.events.application.repository_provider import get_event_store


def count_related_events_by_correlation_ids(correlation_ids: set[str]) -> int:
    """Return the total number of events across the given correlation chains."""

    event_store = get_event_store()
    total = 0
    for correlation_id in correlation_ids:
        total += len(event_store.get_by_correlation(correlation_id))
    return total
