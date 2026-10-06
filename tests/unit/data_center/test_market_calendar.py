"""Provider-backed market-calendar application contracts."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application import market_calendar
from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE
from apps.data_center.domain.model_market_data import TradingCalendarEvidence
from core.exceptions import ConfigurationError
from core.integration.data_center_audit import SystemAuditCompositionUnavailable


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


def test_audit_composition_failure_becomes_calendar_blocker(monkeypatch) -> None:
    """A missing audited writer keeps calendar reads fail closed without a 500."""

    monkeypatch.setattr(
        market_calendar,
        "load_open_cn_market_sessions",
        lambda *_args: (_ for _ in ()).throw(
            SystemAuditCompositionUnavailable(
                "audit runtime missing",
                reason_code="runtime_binding_unavailable",
            )
        ),
    )

    assert (
        market_calendar.latest_completed_cn_market_session(
            datetime(2026, 9, 25, 16, 30, tzinfo=CN_MARKET_TIMEZONE)
        )
        is None
    )


def test_source_bound_calendar_evidence_reuses_exact_coverage_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm readiness reads reuse validated provider evidence without rebuilding its route."""

    from apps.data_center import composition

    start_date = date(2026, 9, 1)
    end_date = date(2026, 9, 30)
    evidence = TradingCalendarEvidence(
        coverage_start=start_date,
        coverage_end=end_date,
        open_sessions=(date(2026, 9, 1),),
        source="fixture-provider",
        observed_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    route_calls: list[tuple[date, date]] = []
    build_calls: list[bool] = []

    class _CalendarPort:
        def trading_calendar_evidence(
            self,
            requested_start: date,
            requested_end: date,
        ) -> TradingCalendarEvidence:
            route_calls.append((requested_start, requested_end))
            return evidence

    def build_calendar_port() -> _CalendarPort:
        build_calls.append(True)
        return _CalendarPort()

    monkeypatch.setattr(composition, "build_model_market_data_service", build_calendar_port)
    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    try:
        first = market_calendar.load_cn_market_calendar_evidence(start_date, end_date)
        second = market_calendar.load_cn_market_calendar_evidence(start_date, end_date)
    finally:
        market_calendar.load_cn_market_calendar_evidence.cache_clear()

    assert first is evidence
    assert second is evidence
    assert route_calls == [(start_date, end_date)]
    assert build_calls == [True]
