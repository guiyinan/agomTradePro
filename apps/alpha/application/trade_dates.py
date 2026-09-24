"""Application-level helpers for Alpha trade-date resolution."""

from __future__ import annotations

from datetime import date, datetime, time

from django.utils import timezone

from apps.data_center.application.market_calendar import latest_cn_market_session_ready_after
from core.exceptions import DataFetchError

POST_CLOSE_HOUR = 16
POST_CLOSE_MINUTE = 0


def resolve_recent_closed_trade_date(reference_dt: datetime | None = None) -> date:
    """Resolve the latest source-observed session whose Alpha inputs should be ready."""

    local_now = timezone.localtime(reference_dt) if reference_dt else timezone.localtime()
    resolved = latest_cn_market_session_ready_after(
        local_now,
        ready_after=time(POST_CLOSE_HOUR, POST_CLOSE_MINUTE),
    )
    if resolved is None:
        raise DataFetchError(
            "Exchange trading calendar is unavailable",
            code="MARKET_CALENDAR_UNAVAILABLE",
        )
    return resolved
