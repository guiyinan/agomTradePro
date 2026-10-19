"""Unit contracts for the opt-in M5 calendar transport's request boundary."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory

from apps.data_center import composition
from apps.data_center.application import market_calendar
from apps.data_center.domain.model_market_data import (
    ModelMarketDataPort,
    TradingCalendarEvidence,
)
from tests.support.tui_research import (
    calendar_transport,
)
from tests.support.tui_research import calendar_transport_runtime as runtime
from tests.support.tui_research.calendar_transport_settings import (
    require_m5_calendar_transport_environment,
)

pytestmark = pytest.mark.unit

_ACTION_KEYS = (
    "data-center.market-thermometer-current",
    "dashboard.alpha-ranking",
    "operator.governance.data_center_summary",
    "task-monitor.readiness",
)
_START = date(2026, 9, 1)
_END = date(2026, 9, 30)
_SESSION = date(2026, 9, 2)
_OBSERVED_AT = datetime(2026, 9, 30, tzinfo=UTC)


def _valid_guard_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    """Install the complete opt-in contract and return matching SQLite settings."""

    runner_temp = tmp_path.resolve()
    database_path = runner_temp / "agomtradepro-rc-playwright.sqlite3"
    artifact_path = runner_temp / "agomtradepro-m5-calendar"
    values = {
        "AGOM_M5_SYNTHETIC_CALENDAR": "1",
        "DJANGO_SETTINGS_MODULE": "core.settings.playwright",
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "RUNNER_TEMP": str(runner_temp),
        "AGOM_PLAYWRIGHT_DB_PATH": str(database_path),
        "AGOM_M5_CALENDAR_ARTIFACT_DIR": str(artifact_path),
        "AGOM_M5_CALENDAR_BASE_URL": "http://127.0.0.1:8765",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(database_path),
            "TEST": {"NAME": str(database_path)},
        }
    }


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("AGOM_M5_SYNTHETIC_CALENDAR", "0"),
        ("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite"),
        ("CI", "false"),
        ("GITHUB_ACTIONS", "false"),
        ("RUNNER_TEMP", "relative-runner-temp"),
        ("AGOM_PLAYWRIGHT_DB_PATH", "D:/unrelated.sqlite3"),
        ("AGOM_M5_CALENDAR_ARTIFACT_DIR", "D:/unrelated-artifacts"),
        ("AGOM_M5_CALENDAR_BASE_URL", "http://localhost:8765"),
        ("AGOM_M5_CALENDAR_BASE_URL", "http://127.0.0.1:8765/path"),
        ("AGOM_M5_CALENDAR_BASE_URL", "http://user@127.0.0.1:8765"),
    ),
)
def test_settings_guard_rejects_unisolated_opt_in_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    """Reject altered flags, paths, and non-literal-loopback URLs."""

    databases = _valid_guard_state(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError):
        require_m5_calendar_transport_environment(databases=databases)


@pytest.mark.parametrize("database_field", ("ENGINE", "NAME", "TEST.NAME"))
def test_settings_guard_rejects_database_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_field: str,
) -> None:
    """Require default and test SQLite databases to share the fixed runner path."""

    databases = _valid_guard_state(monkeypatch, tmp_path)
    default = cast(dict[str, object], databases["default"])
    if database_field == "TEST.NAME":
        test_settings = cast(dict[str, object], default["TEST"])
        test_settings["NAME"] = str(tmp_path / "other-test.sqlite3")
    elif database_field == "NAME":
        default["NAME"] = str(tmp_path / "other.sqlite3")
    else:
        default["ENGINE"] = "django.db.backends.postgresql"

    with pytest.raises(ValueError):
        require_m5_calendar_transport_environment(databases=databases)


def test_artifact_guard_rejects_partial_pair_and_accepts_absent_pair(
    tmp_path: Path,
) -> None:
    """Missing both artifacts is normal, while a half-written pair fails closed."""

    assert runtime._synthetic_artifacts_ready(tmp_path) is False
    (tmp_path / "synthetic-calendar.json").write_bytes(b"{}")
    with pytest.raises(RuntimeError, match="partial M5 synthetic calendar artifact"):
        runtime._synthetic_artifacts_ready(tmp_path)


def test_artifact_loader_rejects_tampered_raw_bytes(tmp_path: Path) -> None:
    """A raw fixture changed after its sidecar was written cannot be consumed."""

    raw_json = json.dumps(
        {
            "coverage_start": _START.isoformat(),
            "coverage_end": _END.isoformat(),
            "open_sessions": [_SESSION.isoformat()],
            "observed_at": _OBSERVED_AT.isoformat(),
            "source": calendar_transport.SYNTHETIC_CALENDAR_SOURCE,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    artifacts = calendar_transport.write_synthetic_calendar_raw(
        raw_json,
        tmp_path=tmp_path,
        coverage_start=_START,
        coverage_end=_END,
        open_sessions=(_SESSION,),
        observed_at=_OBSERVED_AT,
    )
    artifacts.raw_path.write_bytes(raw_json + b" ")

    with pytest.raises(ValueError, match="do not match their SHA-256 sidecar"):
        calendar_transport.build_synthetic_calendar_service_from_artifacts(
            artifact_root=tmp_path,
        )


@pytest.mark.parametrize("action_key", _ACTION_KEYS)
def test_request_middleware_scopes_only_the_exact_allowlisted_run_route(
    action_key: str,
) -> None:
    """Every approved POST is scoped and copied contexts expire at response end."""

    assert runtime._M5_CALENDAR_ACTION_KEYS == frozenset(_ACTION_KEYS)
    request = RequestFactory().post(f"/api/tui/actions/{action_key}/run/", data={})
    captured_contexts: list[Context] = []

    def get_response(_request: HttpRequest) -> HttpResponse:
        assert runtime._calendar_request_scope_is_active()
        captured_contexts.append(copy_context())
        return HttpResponse("ok")

    response = runtime.M5CalendarRequestScopeMiddleware(get_response)(request)

    assert response.status_code == 200
    assert not runtime._calendar_request_scope_is_active()
    assert len(captured_contexts) == 1
    assert captured_contexts[0].run(runtime._calendar_request_scope_is_active) is False


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/tui/actions/data-center.market-thermometer-current/run/"),
        ("POST", "/api/tui/actions/asset-analysis.pool-screen/run/"),
        ("POST", "/api/tui/actions/data-center.market-thermometer-current/schema/"),
        ("POST", "/api/tui/actions/data-center.market-thermometer-current/run/extra/"),
    ),
)
def test_request_middleware_leaves_other_requests_unscoped(
    method: str,
    path: str,
) -> None:
    """Methods, routes, and action keys outside the four-key contract delegate."""

    request = RequestFactory().generic(method, path)
    observed_scope: list[bool] = []

    def get_response(_request: HttpRequest) -> HttpResponse:
        observed_scope.append(runtime._calendar_request_scope_is_active())
        return HttpResponse("ok")

    runtime.M5CalendarRequestScopeMiddleware(get_response)(request)

    assert observed_scope == [False]
    assert not runtime._calendar_request_scope_is_active()


def test_nested_requests_shadow_nonallowlisted_scope_and_restore_outer_action() -> None:
    """Nested unrelated routes cannot borrow scope, and nested actions restore it."""

    middleware = runtime.M5CalendarRequestScopeMiddleware
    outer_request = RequestFactory().post(
        "/api/tui/actions/data-center.market-thermometer-current/run/",
        data={},
    )
    nested_observations: list[bool] = []

    def outer_response(_request: HttpRequest) -> HttpResponse:
        assert runtime._calendar_request_scope_is_active()
        unrelated_request = RequestFactory().post(
            "/api/tui/actions/asset-analysis.pool-screen/run/"
        )
        middleware(
            lambda _nested: (
                nested_observations.append(runtime._calendar_request_scope_is_active())
                or HttpResponse("unrelated")
            )
        )(unrelated_request)
        assert runtime._calendar_request_scope_is_active()

        nested_action_request = RequestFactory().post(
            "/api/tui/actions/dashboard.alpha-ranking/run/",
            data={},
        )
        middleware(
            lambda _nested: (
                nested_observations.append(runtime._calendar_request_scope_is_active())
                or HttpResponse("nested action")
            )
        )(nested_action_request)
        assert runtime._calendar_request_scope_is_active()
        return HttpResponse("outer action")

    middleware(outer_response)(outer_request)

    assert nested_observations == [False, True]
    assert not runtime._calendar_request_scope_is_active()


@pytest.mark.parametrize("action_key", _ACTION_KEYS)
def test_runtime_hook_substitutes_only_inside_exact_action_and_restores_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action_key: str,
) -> None:
    """The real hook delegates for other actions and background calls."""

    artifact_root = tmp_path
    ordinary_service = cast(ModelMarketDataPort, object())
    synthetic_service = cast(ModelMarketDataPort, object())
    evidence = TradingCalendarEvidence(
        coverage_start=_START,
        coverage_end=_END,
        open_sessions=(_SESSION,),
        source="original-loader-test-double",
        observed_at=_OBSERVED_AT,
    )
    factory_results: list[ModelMarketDataPort] = []
    synthetic_builds: list[Path] = []
    loader_contexts: list[Context] = []
    raise_after_factory: list[bool] = [False]

    def original_factory() -> ModelMarketDataPort:
        factory_results.append(ordinary_service)
        return ordinary_service

    @lru_cache(maxsize=8)
    def original_loader(start_date: date, end_date: date) -> TradingCalendarEvidence:
        assert start_date == _START
        assert end_date == _END
        loader_contexts.append(copy_context())
        composition.build_model_market_data_service()
        if raise_after_factory[0]:
            raise RuntimeError("controlled loader failure")
        return evidence

    def build_synthetic(*, artifact_root: Path) -> tuple[ModelMarketDataPort, object]:
        synthetic_builds.append(artifact_root)
        return synthetic_service, object()

    monkeypatch.setattr(runtime, "_INSTALLED", False)
    monkeypatch.setattr(runtime, "_validated_artifact_root", lambda: artifact_root)
    monkeypatch.setattr(
        composition,
        "build_model_market_data_service",
        original_factory,
    )
    monkeypatch.setattr(
        market_calendar,
        "load_cn_market_calendar_evidence",
        original_loader,
    )
    monkeypatch.setattr(
        calendar_transport,
        "build_synthetic_calendar_service_from_artifacts",
        build_synthetic,
    )
    runtime.install_m5_calendar_transport()
    scoped_loader = market_calendar.load_cn_market_calendar_evidence

    no_artifact_request = RequestFactory().post(
        f"/api/tui/actions/{action_key}/run/",
        data={},
    )
    runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
        no_artifact_request
    )
    assert synthetic_builds == []
    assert factory_results == [ordinary_service]

    raw_path = artifact_root / "synthetic-calendar.json"
    sidecar_path = artifact_root / "synthetic-calendar.json.sha256"
    raw_path.write_bytes(b"synthetic")
    scoped_loader.cache_clear()
    unrelated_with_partial_artifact = RequestFactory().post(
        "/api/tui/actions/asset-analysis.pool-screen/run/"
    )
    runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
        unrelated_with_partial_artifact
    )
    assert synthetic_builds == []
    assert factory_results == [ordinary_service, ordinary_service]

    partial_artifact_request = RequestFactory().post(
        f"/api/tui/actions/{action_key}/run/",
        data={},
    )
    with pytest.raises(RuntimeError, match="partial M5 synthetic calendar artifact"):
        runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
            partial_artifact_request
        )
    assert not runtime._calendar_request_scope_is_active()

    sidecar_path.write_text(
        "sidecar",
        encoding="ascii",
    )
    allowed_request = RequestFactory().post(
        f"/api/tui/actions/{action_key}/run/",
        data={},
    )
    runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
        allowed_request
    )
    assert synthetic_builds == [artifact_root]
    assert factory_results == [ordinary_service, ordinary_service]
    assert not runtime._calendar_request_scope_is_active()
    assert loader_contexts[-1].run(composition.build_model_market_data_service) is ordinary_service
    assert factory_results == [ordinary_service] * 3
    allowed_cache_info = cast(
        tuple[int, int, int, int],
        scoped_loader.cache_info(),
    )
    assert allowed_cache_info[3] == 0

    other_request = RequestFactory().post("/api/tui/actions/asset-analysis.pool-screen/run/")
    runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
        other_request
    )
    assert synthetic_builds == [artifact_root]
    assert factory_results == [ordinary_service] * 4

    composition.build_model_market_data_service()
    assert factory_results == [ordinary_service] * 5
    assert not runtime._calendar_request_scope_is_active()

    raise_after_factory[0] = True
    failing_request = RequestFactory().post(
        f"/api/tui/actions/{action_key}/run/",
        data={},
    )
    with pytest.raises(RuntimeError, match="controlled loader failure"):
        runtime.M5CalendarRequestScopeMiddleware(lambda _request: scoped_loader(_START, _END))(
            failing_request
        )
    assert not runtime._calendar_request_scope_is_active()
    assert loader_contexts[-1].run(composition.build_model_market_data_service) is ordinary_service
    failed_cache_info = cast(
        tuple[int, int, int, int],
        scoped_loader.cache_info(),
    )
    assert failed_cache_info[3] == 0
    assert factory_results == [ordinary_service] * 6
    assert synthetic_builds == [artifact_root, artifact_root]


def test_unscoped_loader_waits_until_synthetic_cache_is_cleared(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An ordinary concurrent call cannot observe the scoped cache entry."""

    artifact_root = tmp_path
    synthetic_entered = Event()
    release_synthetic_loader = Event()
    final_cache_clear_entered = Event()
    release_final_cache_clear = Event()
    ordinary_loader_entered = Event()
    unscoped_lock_contended = Event()
    unscoped_original_loader_entered = Event()
    unscoped_call_started = Event()
    unscoped_call_returned = Event()
    synthetic_evidence = TradingCalendarEvidence(
        coverage_start=_START,
        coverage_end=_END,
        open_sessions=(_SESSION,),
        source="synthetic-loader-race-test",
        observed_at=_OBSERVED_AT,
    )
    ordinary_evidence = TradingCalendarEvidence(
        coverage_start=_START,
        coverage_end=_END,
        open_sessions=(_SESSION,),
        source="ordinary-loader-race-test",
        observed_at=_OBSERVED_AT,
    )
    ordinary_service = cast(ModelMarketDataPort, object())
    synthetic_service = cast(ModelMarketDataPort, object())
    services: list[ModelMarketDataPort] = []
    cache_clear_calls = 0
    real_rlock_factory = runtime.RLock

    class ObservedRLock:
        def __init__(self) -> None:
            self._lock = real_rlock_factory()

        def __enter__(self) -> ObservedRLock:
            if not self._lock.acquire(blocking=False):
                if not runtime._calendar_request_scope_is_active():
                    unscoped_lock_contended.set()
                self._lock.acquire()
            return self

        def __exit__(self, *_args: object) -> None:
            self._lock.release()

    @lru_cache(maxsize=8)
    def cached_original_loader(
        start_date: date,
        end_date: date,
    ) -> TradingCalendarEvidence:
        assert start_date == _START
        assert end_date == _END
        service = composition.build_model_market_data_service()
        services.append(service)
        if runtime._calendar_request_scope_is_active():
            synthetic_entered.set()
            if not release_synthetic_loader.wait(timeout=3):
                raise TimeoutError("synthetic loader release timed out")
            return synthetic_evidence
        ordinary_loader_entered.set()
        return ordinary_evidence

    def original_loader(start_date: date, end_date: date) -> TradingCalendarEvidence:
        if not runtime._calendar_request_scope_is_active():
            unscoped_original_loader_entered.set()
        return cached_original_loader(start_date, end_date)

    def controlled_cache_clear() -> None:
        nonlocal cache_clear_calls
        cache_clear_calls += 1
        if cache_clear_calls == 2:
            final_cache_clear_entered.set()
            if not release_final_cache_clear.wait(timeout=3):
                raise TimeoutError("final cache-clear release timed out")
        cached_original_loader.cache_clear()

    original_loader.cache_clear = controlled_cache_clear
    original_loader.cache_info = cached_original_loader.cache_info
    original_loader.cache_parameters = cached_original_loader.cache_parameters

    def original_factory() -> ModelMarketDataPort:
        return ordinary_service

    def build_synthetic(*, artifact_root: Path) -> tuple[ModelMarketDataPort, object]:
        assert artifact_root == tmp_path
        return synthetic_service, object()

    monkeypatch.setattr(runtime, "_INSTALLED", False)
    monkeypatch.setattr(runtime, "RLock", ObservedRLock)
    monkeypatch.setattr(runtime, "_validated_artifact_root", lambda: artifact_root)
    monkeypatch.setattr(runtime, "_synthetic_artifacts_ready", lambda _root: True)
    monkeypatch.setattr(
        composition,
        "build_model_market_data_service",
        original_factory,
    )
    monkeypatch.setattr(
        market_calendar,
        "load_cn_market_calendar_evidence",
        original_loader,
    )
    monkeypatch.setattr(
        calendar_transport,
        "build_synthetic_calendar_service_from_artifacts",
        build_synthetic,
    )
    runtime.install_m5_calendar_transport()
    scoped_loader = market_calendar.load_cn_market_calendar_evidence

    def run_allowlisted_request() -> HttpResponse:
        request = RequestFactory().post(
            "/api/tui/actions/data-center.market-thermometer-current/run/",
            data={},
        )

        def get_response(_request: HttpRequest) -> HttpResponse:
            result = scoped_loader(_START, _END)
            assert isinstance(result, TradingCalendarEvidence)
            scoped_results.append(result)
            return HttpResponse("ok")

        return runtime.M5CalendarRequestScopeMiddleware(get_response)(request)

    scoped_results: list[TradingCalendarEvidence] = []

    def run_unscoped_call() -> TradingCalendarEvidence:
        unscoped_call_started.set()
        try:
            return Context().run(scoped_loader, _START, _END)
        finally:
            unscoped_call_returned.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        scoped_future = executor.submit(run_allowlisted_request)
        try:
            assert synthetic_entered.wait(timeout=2)
            release_synthetic_loader.set()
            assert final_cache_clear_entered.wait(timeout=2)
            unscoped_future = executor.submit(run_unscoped_call)
            assert unscoped_call_started.wait(timeout=2)
            assert unscoped_lock_contended.wait(timeout=2)
            assert not unscoped_call_returned.wait(timeout=0.2)
            assert not unscoped_original_loader_entered.is_set()
            assert not ordinary_loader_entered.is_set()
        finally:
            release_synthetic_loader.set()
            release_final_cache_clear.set()

        assert scoped_future.result(timeout=3).status_code == 200
        assert scoped_results == [synthetic_evidence]
        assert unscoped_future.result(timeout=3) is ordinary_evidence

    assert services == [synthetic_service, ordinary_service]
    assert cache_clear_calls == 2
    assert unscoped_original_loader_entered.is_set()
    assert ordinary_loader_entered.is_set()
    assert not runtime._calendar_request_scope_is_active()
