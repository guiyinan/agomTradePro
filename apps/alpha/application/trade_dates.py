"""Application-level helpers for Alpha trade-date resolution."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone

POST_CLOSE_HOUR = 16
POST_CLOSE_MINUTE = 0


def previous_business_day(target_date: date) -> date:
    """Return the previous weekday for post-close scheduling fallbacks."""

    previous_day = target_date - timedelta(days=1)
    while previous_day.weekday() >= 5:
        previous_day -= timedelta(days=1)
    return previous_day


def resolve_recent_closed_trade_date(reference_dt: datetime | None = None) -> date:
    """Resolve the most recent trade date that should already have post-close data."""

    local_now = timezone.localtime(reference_dt) if reference_dt else timezone.localtime()
    current_date = local_now.date()

    if current_date.weekday() >= 5:
        return previous_business_day(current_date)

    if (local_now.hour, local_now.minute) < (POST_CLOSE_HOUR, POST_CLOSE_MINUTE):
        return previous_business_day(current_date)

    return current_date
