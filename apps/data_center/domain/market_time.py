"""Canonical time boundaries for mainland-China market dates."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone

CN_MARKET_TIMEZONE = timezone(timedelta(hours=8))
CN_MARKET_OPEN = time(9, 30)
CN_MARKET_CLOSE = time(15, 0)


def _previous_weekday(target_date: date) -> date:
    """Return the latest weekday before ``target_date``."""

    previous_day = target_date - timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= timedelta(days=1)
    return previous_day


def latest_completed_cn_market_session(now: datetime) -> date | None:
    """Return the latest completed mainland-China weekday session."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_now = now.astimezone(CN_MARKET_TIMEZONE)
    current_date = local_now.date()
    if current_date.weekday() >= 5:
        return _previous_weekday(current_date)
    current_time = local_now.time()
    if current_time < CN_MARKET_OPEN:
        return _previous_weekday(current_date)
    if current_time >= CN_MARKET_CLOSE:
        return current_date
    return None


def latest_closed_cn_market_session(now: datetime) -> date:
    """Return the latest closed weekday session, including during live trading."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("market clock must be timezone-aware")
    local_now = now.astimezone(CN_MARKET_TIMEZONE)
    current_date = local_now.date()
    if current_date.weekday() >= 5:
        return _previous_weekday(current_date)
    if local_now.time() >= CN_MARKET_CLOSE:
        return current_date
    return _previous_weekday(current_date)


def cn_market_date_start_utc(value: date) -> datetime:
    """Return the UTC instant at which a China-market calendar date starts."""

    return datetime.combine(value, time.min, tzinfo=CN_MARKET_TIMEZONE).astimezone(UTC)


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
    "latest_closed_cn_market_session",
    "latest_completed_cn_market_session",
]
