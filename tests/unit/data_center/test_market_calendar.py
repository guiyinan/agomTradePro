"""Provider-backed market-calendar application contracts."""

from datetime import date, datetime

from apps.data_center.application import market_calendar
from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE
from core.exceptions import ConfigurationError


def test_completed_session_skips_weekday_exchange_holiday(monkeypatch) -> None:
    """The application resolver uses source sessions instead of weekday guesses."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 28)),
    )

    resolved = market_calendar.latest_completed_cn_market_session(
        datetime(2026, 9, 25, 16, 30, tzinfo=CN_MARKET_TIMEZONE)
    )

    assert resolved == date(2026, 9, 24)


def test_post_close_readiness_skips_extended_holiday(monkeypatch) -> None:
    """A post-close consumer selects the latest observed session across a holiday."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 8)),
    )

    resolved = market_calendar.latest_cn_market_session_ready_after(
        datetime(2026, 10, 8, 9, 0, tzinfo=CN_MARKET_TIMEZONE),
        ready_after=datetime.strptime("16:00", "%H:%M").time(),
    )

    assert resolved == date(2026, 9, 30)


def test_calendar_unavailable_fails_closed(monkeypatch) -> None:
    """Missing provider evidence never falls back to a manufactured weekday."""

    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: ())

    assert (
        market_calendar.latest_completed_cn_market_session(
            datetime(2026, 9, 25, 16, 30, tzinfo=CN_MARKET_TIMEZONE)
        )
        is None
    )


def test_provider_configuration_failure_becomes_calendar_blocker(monkeypatch) -> None:
    """A missing provider policy produces no guessed weekday or uncaught exception."""

    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    monkeypatch.setattr(
        market_calendar,
        "load_open_cn_market_sessions",
        lambda *_args: (_ for _ in ()).throw(ConfigurationError("policy missing")),
    )

    assert (
        market_calendar.latest_completed_cn_market_session(
            datetime(2026, 9, 25, 16, 30, tzinfo=CN_MARKET_TIMEZONE)
        )
        is None
    )
