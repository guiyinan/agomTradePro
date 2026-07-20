"""Pure date helpers shared by market-data freshness checks."""

from __future__ import annotations

from datetime import date, timedelta


def business_day_age(observed_at: date, as_of_date: date) -> int:
    """Count weekdays after ``observed_at`` through ``as_of_date``.

    This deliberately excludes weekends without pretending to know exchange
    holidays. Consumers that own a trading calendar should use that richer
    calendar; generic market-data freshness checks use this conservative
    weekday baseline so Saturday and Sunday never consume the stale budget.
    """

    if as_of_date <= observed_at:
        return 0
    current = observed_at + timedelta(days=1)
    age = 0
    while current <= as_of_date:
        if current.weekday() < 5:
            age += 1
        current += timedelta(days=1)
    return age
