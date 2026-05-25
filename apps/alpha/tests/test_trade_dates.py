from datetime import datetime, timezone

from apps.alpha.application.trade_dates import resolve_recent_closed_trade_date


def test_resolve_recent_closed_trade_date_uses_previous_business_day_before_close():
    reference_dt = datetime(2026, 5, 25, 3, 30, tzinfo=timezone.utc)

    assert resolve_recent_closed_trade_date(reference_dt) == datetime(2026, 5, 22, 0, 0).date()


def test_resolve_recent_closed_trade_date_uses_same_day_after_close():
    reference_dt = datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)

    assert resolve_recent_closed_trade_date(reference_dt) == datetime(2026, 5, 25, 0, 0).date()


def test_resolve_recent_closed_trade_date_uses_previous_business_day_on_weekend():
    reference_dt = datetime(2026, 5, 24, 3, 30, tzinfo=timezone.utc)

    assert resolve_recent_closed_trade_date(reference_dt) == datetime(2026, 5, 22, 0, 0).date()
