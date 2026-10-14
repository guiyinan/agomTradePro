"""Provider-backed market-calendar application contracts."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.application import market_calendar
from apps.data_center.domain.market_time import CN_MARKET_TIMEZONE
from apps.data_center.domain.model_market_data import TradingCalendarEvidence
from core.exceptions import ConfigurationError, DataFetchError
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


@pytest.mark.parametrize(
    "local_now",
    (
        datetime(2026, 10, 12, 9, 15, tzinfo=CN_MARKET_TIMEZONE),
        datetime(2026, 10, 12, 13, 0, tzinfo=CN_MARKET_TIMEZONE),
        datetime(2026, 10, 12, 16, 59, tzinfo=CN_MARKET_TIMEZONE),
    ),
    ids=("provider-rollover", "open-session", "post-close-provider-delay"),
)
def test_full_market_session_waits_for_provider_ready_boundary(
    monkeypatch: pytest.MonkeyPatch,
    local_now: datetime,
) -> None:
    """Full-market refresh does not mix an intraday source with an older target."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 10, 9), date(2026, 10, 12)),
    )

    with pytest.raises(
        DataFetchError,
        match="Full-market providers are not ready",
    ) as exc_info:
        market_calendar.latest_full_market_provider_ready_session(local_now)

    assert exc_info.value.code == "CURRENT_MARKET_PROVIDER_WINDOW_NOT_READY"


@pytest.mark.parametrize(
    "local_now",
    (
        datetime(2026, 10, 12, 0, 0, tzinfo=CN_MARKET_TIMEZONE),
        datetime(2026, 10, 12, 7, 30, tzinfo=CN_MARKET_TIMEZONE),
        datetime(2026, 10, 12, 9, 14, 59, tzinfo=CN_MARKET_TIMEZONE),
    ),
    ids=("midnight", "pre-open", "before-provider-rollover"),
)
def test_full_market_session_uses_previous_ready_session_before_provider_rollover(
    monkeypatch: pytest.MonkeyPatch,
    local_now: datetime,
) -> None:
    """Before Tencent starts the current session, yesterday remains exact provider data."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 10, 9), date(2026, 10, 12)),
    )

    resolved = market_calendar.latest_full_market_provider_ready_session(local_now)

    assert resolved == date(2026, 10, 9)


def test_full_market_session_opens_at_provider_ready_boundary(monkeypatch) -> None:
    """The target becomes eligible at the shared 17:05 China-market boundary."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 10, 9), date(2026, 10, 12)),
    )

    resolved = market_calendar.latest_full_market_provider_ready_session(
        datetime(2026, 10, 12, 17, 5, tzinfo=CN_MARKET_TIMEZONE)
    )

    assert resolved == date(2026, 10, 12)


def test_isolated_s6_uses_previous_ready_session_during_provider_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An isolated S6 run may rehearse yesterday while production remains blocked."""

    sessions = (date(2026, 10, 9), date(2026, 10, 12))
    local_now = datetime(2026, 10, 12, 13, 0, tzinfo=CN_MARKET_TIMEZONE)
    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: sessions)

    target_session = market_calendar.latest_cn_market_session_ready_after(
        local_now,
        ready_after=market_calendar.FULL_MARKET_PROVIDER_READY_AFTER,
    )
    with market_calendar.isolated_s6_full_market_provider_session(
        target_session,
        triggered_at=local_now,
    ):
        resolved = market_calendar.latest_full_market_provider_ready_session(local_now)

    assert resolved == date(2026, 10, 9)
    with pytest.raises(DataFetchError) as exc_info:
        market_calendar.latest_full_market_provider_ready_session(local_now)
    assert exc_info.value.code == "CURRENT_MARKET_PROVIDER_WINDOW_NOT_READY"


def test_isolated_s6_uses_current_session_at_provider_ready_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The isolated S6 target advances to today exactly at 17:05 China time."""

    sessions = (date(2026, 10, 9), date(2026, 10, 12))
    local_now = datetime(2026, 10, 12, 17, 5, tzinfo=CN_MARKET_TIMEZONE)
    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: sessions)

    target_session = market_calendar.latest_cn_market_session_ready_after(
        local_now,
        ready_after=market_calendar.FULL_MARKET_PROVIDER_READY_AFTER,
    )
    with market_calendar.isolated_s6_full_market_provider_session(
        target_session,
        triggered_at=local_now,
    ):
        resolved = market_calendar.latest_full_market_provider_ready_session(local_now)

    assert resolved == date(2026, 10, 12)


def test_isolated_s6_rejects_a_target_other_than_latest_ready_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit isolated override cannot select stale or future session evidence."""

    sessions = (date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12))
    local_now = datetime(2026, 10, 12, 13, 0, tzinfo=CN_MARKET_TIMEZONE)
    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: sessions)

    with market_calendar.isolated_s6_full_market_provider_session(
        date(2026, 10, 8),
        triggered_at=local_now,
    ):
        with pytest.raises(DataFetchError) as exc_info:
            market_calendar.latest_full_market_provider_ready_session(local_now)

    assert exc_info.value.code == "ISOLATED_S6_MARKET_SESSION_NOT_READY"


def test_isolated_s6_target_resets_after_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed isolated refresh cannot leak its target into later production work."""

    sessions = (date(2026, 10, 9), date(2026, 10, 12))
    local_now = datetime(2026, 10, 12, 13, 0, tzinfo=CN_MARKET_TIMEZONE)
    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: sessions)

    with pytest.raises(RuntimeError, match="simulated refresh failure"):
        with market_calendar.isolated_s6_full_market_provider_session(
            date(2026, 10, 9),
            triggered_at=local_now,
        ):
            raise RuntimeError("simulated refresh failure")

    with pytest.raises(DataFetchError) as exc_info:
        market_calendar.latest_full_market_provider_ready_session(local_now)
    assert exc_info.value.code == "CURRENT_MARKET_PROVIDER_WINDOW_NOT_READY"


def test_isolated_s6_keeps_trigger_time_target_across_ready_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run triggered before 17:05 keeps yesterday if execution crosses 17:05."""

    sessions = (date(2026, 10, 9), date(2026, 10, 12))
    triggered_at = datetime(2026, 10, 12, 17, 4, 59, tzinfo=CN_MARKET_TIMEZONE)
    task_now = datetime(2026, 10, 12, 17, 5, 1, tzinfo=CN_MARKET_TIMEZONE)
    monkeypatch.setattr(market_calendar, "_open_sessions_for", lambda _now: sessions)

    with market_calendar.isolated_s6_full_market_provider_session(
        date(2026, 10, 9),
        triggered_at=triggered_at,
    ):
        resolved = market_calendar.latest_full_market_provider_ready_session(task_now)

    assert resolved == date(2026, 10, 9)


def test_full_market_session_remains_available_on_non_session_day(monkeypatch) -> None:
    """A weekend may still rehearse the latest provider-ready closed session."""

    monkeypatch.setattr(
        market_calendar,
        "_open_sessions_for",
        lambda _now: (date(2026, 10, 9),),
    )

    resolved = market_calendar.latest_full_market_provider_ready_session(
        datetime(2026, 10, 11, 13, 0, tzinfo=CN_MARKET_TIMEZONE)
    )

    assert resolved == date(2026, 10, 9)


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
