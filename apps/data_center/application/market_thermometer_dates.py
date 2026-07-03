"""Decision-safe date resolution for market thermometer jobs and reads."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MARKET_THERMOMETER_POST_CLOSE_HOUR = 16
MARKET_THERMOMETER_POST_CLOSE_MINUTE = 0
MARKET_THERMOMETER_TIMEZONE = ZoneInfo("Asia/Shanghai")


def previous_business_day(target_date: date) -> date:
    """Return the latest weekday before ``target_date``."""

    previous_day = target_date - timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= timedelta(days=1)
    return previous_day


def resolve_market_thermometer_as_of_date(
    raw_as_of_date: str = "",
    *,
    now: datetime | None = None,
) -> date:
    """Resolve the latest market date that is safe for decision-grade reads/writes."""

    normalized = str(raw_as_of_date or "").strip()
    if normalized:
        return date.fromisoformat(normalized)

    local_now = now or datetime.now(MARKET_THERMOMETER_TIMEZONE)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=MARKET_THERMOMETER_TIMEZONE)
    else:
        local_now = local_now.astimezone(MARKET_THERMOMETER_TIMEZONE)

    current_date = local_now.date()
    if current_date.weekday() >= 5:
        return previous_business_day(current_date)
    if (local_now.hour, local_now.minute) < (
        MARKET_THERMOMETER_POST_CLOSE_HOUR,
        MARKET_THERMOMETER_POST_CLOSE_MINUTE,
    ):
        return previous_business_day(current_date)
    return current_date
