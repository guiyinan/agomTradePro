"""Canonical time boundaries for mainland-China market dates."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

CN_MARKET_TIMEZONE = timezone(timedelta(hours=8))


def cn_market_date_start_utc(value: date) -> datetime:
    """Return the UTC instant at which a China-market calendar date starts."""

    return datetime.combine(value, time.min, tzinfo=CN_MARKET_TIMEZONE).astimezone(UTC)


def cn_market_date_from_observation(value: datetime) -> date:
    """Project an aware observation timestamp onto its China-market date."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation timestamp must be timezone-aware")
    return value.astimezone(CN_MARKET_TIMEZONE).date()


__all__ = [
    "CN_MARKET_TIMEZONE",
    "cn_market_date_from_observation",
    "cn_market_date_start_utc",
]
