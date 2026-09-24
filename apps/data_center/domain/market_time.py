"""Canonical time boundaries for mainland-China market dates."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, date, datetime, time, timedelta, timezone

CN_MARKET_TIMEZONE = timezone(timedelta(hours=8))
CN_MARKET_OPEN = time(9, 30)
CN_MARKET_CLOSE = time(15, 0)


def _latest_open_session(*, target_date: date, open_sessions: Collection[date]) -> date | None:
    """Return the latest source-observed session on or before ``target_date``."""

    eligible = tuple(session for session in open_sessions if session <= target_date)
    return max(eligible) if eligible else None


def latest_completed_cn_market_session(
    now: datetime, *, open_sessions: Collection[date]
) -> date | None:
    """Return the latest source-observed completed mainland-China session."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_now = now.astimezone(CN_MARKET_TIMEZONE)
    current_date = local_now.date()
    current_time = local_now.time()
    if CN_MARKET_OPEN <= current_time < CN_MARKET_CLOSE and current_date in open_sessions:
        return None
    cutoff = current_date if current_time >= CN_MARKET_CLOSE else current_date - timedelta(days=1)
    return _latest_open_session(target_date=cutoff, open_sessions=open_sessions)


def latest_closed_cn_market_session(
    now: datetime, *, open_sessions: Collection[date]
) -> date | None:
    """Return the latest source-observed closed session, including during trading."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_now = now.astimezone(CN_MARKET_TIMEZONE)
    current_date = local_now.date()
    cutoff = (
        current_date if local_now.time() >= CN_MARKET_CLOSE else current_date - timedelta(days=1)
    )
    return _latest_open_session(target_date=cutoff, open_sessions=open_sessions)


def cn_market_date_start_utc(value: date) -> datetime:
    """Return the UTC instant at which a China-market calendar date starts."""

    return datetime.combine(value, time.min, tzinfo=CN_MARKET_TIMEZONE).astimezone(UTC)


def cn_market_session_close_utc(value: date) -> datetime:
    """Return the canonical close instant for a mainland-China market session."""

    return datetime.combine(value, CN_MARKET_CLOSE, tzinfo=CN_MARKET_TIMEZONE).astimezone(UTC)


def cn_market_date_from_observation(value: datetime) -> date:
    """Project an aware observation timestamp onto its China-market date."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation timestamp must be timezone-aware")
    return value.astimezone(CN_MARKET_TIMEZONE).date()


__all__ = [
    "CN_MARKET_CLOSE",
    "CN_MARKET_OPEN",
    "CN_MARKET_TIMEZONE",
    "cn_market_date_from_observation",
    "cn_market_date_start_utc",
    "cn_market_session_close_utc",
    "latest_closed_cn_market_session",
    "latest_completed_cn_market_session",
]
