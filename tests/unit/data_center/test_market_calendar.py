"""Provider-backed market-calendar application contracts."""

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from apps.data_center.application import market_calendar
from apps.data_center.domain.enums import DataCapability
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
    """The pure calendar composition preserves coverage and skips price-audit construction."""

    from apps.data_center import composition
    from apps.data_center.application import interface_services
    from apps.data_center.calendar_evidence_composition import build_calendar_evidence_port
    from apps.data_center.infrastructure import model_market_wiring

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
    build_calls: list[tuple[object, object, dict[str, object], object | None]] = []
    price_writer_calls: list[bool] = []
    registry = object()
    repository = object()
    settings: dict[str, object] = {"status": "active"}

    class _CalendarPort:
        def trading_calendar_evidence(
            self,
            requested_start: date,
            requested_end: date,
        ) -> TradingCalendarEvidence:
            route_calls.append((requested_start, requested_end))
            return evidence

    def build_calendar_port(
        supplied_registry: object,
        supplied_repository: object,
        supplied_settings: dict[str, object],
        *,
        history_fetch_audit: object | None = None,
    ) -> _CalendarPort:
        build_calls.append(
            (supplied_registry, supplied_repository, supplied_settings, history_fetch_audit)
        )
        return _CalendarPort()

    def unexpected_price_writer(**_kwargs: object) -> None:
        price_writer_calls.append(True)
        raise SystemAuditCompositionUnavailable(
            "price audit runtime missing",
            reason_code="runtime_binding_unavailable",
        )

    monkeypatch.setattr(composition, "get_provider_registry", lambda: registry)
    monkeypatch.setattr(composition, "get_price_bar_repository", lambda: repository)
    monkeypatch.setattr(
        interface_services,
        "load_provider_settings_payload",
        lambda: settings,
    )
    monkeypatch.setattr(
        model_market_wiring,
        "build_model_market_service",
        build_calendar_port,
    )
    monkeypatch.setattr(
        composition,
        "make_system_audited_sync_price_use_case",
        unexpected_price_writer,
    )
    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    try:
        first = market_calendar.load_cn_market_calendar_evidence(start_date, end_date)
        second = market_calendar.load_cn_market_calendar_evidence(start_date, end_date)
    finally:
        market_calendar.load_cn_market_calendar_evidence.cache_clear()

    assert first is evidence
    assert second is evidence
    assert route_calls == [(start_date, end_date)]
    assert build_calls == [(registry, repository, settings, None)]
    assert price_writer_calls == []

    def build_invalid_calendar_port(
        _registry: object,
        _repository: object,
        _settings: dict[str, object],
        *,
        history_fetch_audit: object | None = None,
    ) -> object:
        """Supply an invalid service to exercise the composition's typed boundary."""

        return object()

    monkeypatch.setattr(
        model_market_wiring,
        "build_model_market_service",
        build_invalid_calendar_port,
    )
    with pytest.raises(DataFetchError) as exc_info:
        build_calendar_evidence_port()

    assert exc_info.value.code == "MODEL_MARKET_CALENDAR_EVIDENCE_UNAVAILABLE"


@pytest.mark.django_db
def test_audit_off_calendar_composition_uses_configured_provider_and_blocks_price_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real registry route serves calendar evidence while price preparation stays blocked."""

    from apps.data_center import composition, provider_runtime
    from apps.data_center.application import interface_services
    from apps.data_center.calendar_evidence_composition import build_calendar_evidence_port
    from apps.data_center.domain.model_market_data import TradingCalendarEvidencePort
    from apps.data_center.infrastructure import _provider_adapter_akshare
    from apps.data_center.infrastructure.models import ProviderConfigModel

    provider_name = "calendar-audit-off-test"
    ProviderConfigModel.objects.create(
        name=provider_name,
        source_type="akshare",
        is_active=True,
        priority=1,
    )
    start_date = date(2026, 9, 1)
    end_date = date(2026, 9, 30)

    class _FakeAkshareClient:
        def __init__(self) -> None:
            self.calendar_calls = 0
            self.history_calls = 0

        def tool_trade_date_hist_sina(self) -> pd.DataFrame:
            """Return a deterministic provider calendar response for this test."""

            self.calendar_calls += 1
            return pd.DataFrame({"trade_date": ("2026-09-01", "2026-09-30")})

        def stock_zh_a_hist(self, *args: object, **kwargs: object) -> pd.DataFrame:
            """Record an unexpected history request without accessing the network."""

            self.history_calls += 1
            raise AssertionError("audit-off calendar read attempted a price fetch")

    fake_client = _FakeAkshareClient()
    writer_calls: list[bool] = []

    def unexpected_price_writer(**_kwargs: object) -> object:
        """Fail if calendar composition constructs the unrelated price writer."""

        writer_calls.append(True)
        raise AssertionError("calendar composition constructed a price writer")

    monkeypatch.setattr(
        _provider_adapter_akshare,
        "get_akshare_module",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        interface_services,
        "load_provider_settings_payload",
        lambda: {
            "status": "active",
            "default_source": "akshare",
            "enable_failover": False,
            "failover_tolerance": 0.01,
        },
    )
    monkeypatch.setattr(
        composition,
        "make_system_audited_sync_price_use_case",
        unexpected_price_writer,
    )
    provider_runtime.reset_registry()
    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    try:
        registry = provider_runtime.get_registry()
        configured_provider = registry.get_provider(DataCapability.HISTORICAL_PRICE)
        assert configured_provider is not None
        assert configured_provider.provider_name() == provider_name

        before_observation = datetime.now(UTC)
        evidence = market_calendar.load_cn_market_calendar_evidence(start_date, end_date)
        after_observation = datetime.now(UTC)

        assert evidence.coverage_start == start_date
        assert evidence.coverage_end == end_date
        assert evidence.open_sessions == (start_date, end_date)
        assert evidence.source == "akshare"
        assert before_observation <= evidence.observed_at <= after_observation
        assert evidence.observed_at.tzinfo is not None
        assert fake_client.calendar_calls == 1

        service = build_calendar_evidence_port()
        assert isinstance(service, TradingCalendarEvidencePort)
        with pytest.raises(DataFetchError) as exc_info:
            service.prepare_stock_history(("000001.SZ",), start_date, end_date)

        assert exc_info.value.code == "MODEL_MARKET_AUDIT_EVIDENCE_MISSING"
        assert fake_client.history_calls == 0
        assert writer_calls == []
    finally:
        market_calendar.load_cn_market_calendar_evidence.cache_clear()
        provider_runtime.reset_registry()
