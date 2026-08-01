"""Observation and fetch provenance helpers for current quote reads."""

from __future__ import annotations

from datetime import UTC, datetime


def normalize_quote_fetch_provenance(
    snapshot_at: datetime,
    fetched_at: datetime | None,
) -> tuple[datetime | None, bool]:
    """Normalize fetch evidence and report whether observation provenance is invalid."""

    normalized_fetched_at = fetched_at
    if normalized_fetched_at is not None:
        if normalized_fetched_at.tzinfo is None:
            normalized_fetched_at = normalized_fetched_at.replace(tzinfo=UTC)
        else:
            normalized_fetched_at = normalized_fetched_at.astimezone(UTC)
    provenance_invalid = normalized_fetched_at is None or normalized_fetched_at < snapshot_at
    return normalized_fetched_at, provenance_invalid
