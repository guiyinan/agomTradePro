"""Decision-safe date resolution for market thermometer jobs and reads."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from apps.data_center.application.market_calendar import latest_cn_market_session_ready_after
from core.exceptions import DataFetchError

MARKET_THERMOMETER_POST_CLOSE_HOUR = 16
MARKET_THERMOMETER_POST_CLOSE_MINUTE = 0
MARKET_THERMOMETER_TIMEZONE = ZoneInfo("Asia/Shanghai")


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

    resolved = latest_cn_market_session_ready_after(
        local_now,
        ready_after=time(
            MARKET_THERMOMETER_POST_CLOSE_HOUR,
            MARKET_THERMOMETER_POST_CLOSE_MINUTE,
        ),
    )
    if resolved is None:
        raise DataFetchError(
            "Exchange trading calendar is unavailable",
            code="MARKET_CALENDAR_UNAVAILABLE",
        )
    return resolved
