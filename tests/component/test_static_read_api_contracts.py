"""Published static read endpoints must fail closed without server errors."""

from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from apps.data_center import calendar_evidence_composition
from apps.data_center.application import market_calendar
from apps.data_center.domain.model_market_data import TradingCalendarEvidence
from apps.realtime.application.price_polling_service import PricePollingUseCase
from apps.risk_center.application import scenario_public
from apps.risk_center.application.scenario_ports import ScenarioQueryRepositoryProtocol
from apps.risk_center.domain.scenarios import (
    ScenarioDefinition,
    ScenarioRevision,
    ScenarioSetRevision,
    ScenarioType,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)


@pytest.fixture(autouse=True)
def _fast_password_hasher_for_static_read_api_contracts() -> Iterator[None]:
    """Use fast disposable-user hashing while retaining forced-login route coverage."""
    with override_settings(
        PASSWORD_HASHERS=[
            "django.contrib.auth.hashers.MD5PasswordHasher",
            *settings.PASSWORD_HASHERS,
        ]
    ):
        yield None


class _EmptyScenarioQueryRepository(ScenarioQueryRepositoryProtocol):
    """Provide an empty catalog while preserving the real list use case and view."""

    def __init__(self) -> None:
        """Record only the two catalog queries expected from a list request."""
        self.definition_calls: list[bool] = []
        self.current_revision_calls: list[tuple[ScenarioType | None, bool]] = []

    def list_definitions(
        self,
        *,
        include_retired: bool = False,
    ) -> tuple[ScenarioDefinition, ...]:
        """Return no definitions and record the requested retirement scope."""
        self.definition_calls.append(include_retired)
        return ()

    def list_current_revisions(
        self,
        *,
        scenario_type: ScenarioType | None = None,
        include_inactive: bool = False,
    ) -> tuple[ScenarioRevision, ...]:
        """Return no revisions and record the requested type/status scope."""
        self.current_revision_calls.append((scenario_type, include_inactive))
        return ()

    def get_revision(
        self,
        identifier: str,
        *,
        version: int | None = None,
    ) -> ScenarioRevision | None:
        """Reject an unexpected single-revision read from the list endpoint."""
        del identifier, version
        raise AssertionError("scenario list unexpectedly requested a revision")

    def list_revisions(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        """Reject an unexpected revision-history read from the list endpoint."""
        del identifier
        raise AssertionError("scenario list unexpectedly requested revision history")

    def get_active_set_revision(
        self,
        *,
        environment: str,
        purpose: str,
    ) -> ScenarioSetRevision | None:
        """Reject an unexpected active-set read from the list endpoint."""
        del environment, purpose
        raise AssertionError("scenario list unexpectedly requested an active set")


class _StaticCalendarEvidencePort:
    """Provide deterministic typed coverage for static API contract requests."""

    def trading_calendar_evidence(
        self,
        start_date: date,
        end_date: date,
    ) -> TradingCalendarEvidence:
        """Return explicit sessions and the exact caller-requested calendar window."""

        sessions = tuple(
            day for day in (end_date - timedelta(days=1), end_date) if start_date <= day <= end_date
        )
        return TradingCalendarEvidence(
            coverage_start=start_date,
            coverage_end=end_date,
            open_sessions=sessions,
            source="static-get-contract-fixture",
            observed_at=datetime.now(UTC),
        )


def _install_static_calendar_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject deterministic source evidence without bypassing HTTP routing."""

    monkeypatch.setattr(
        calendar_evidence_composition,
        "build_calendar_evidence_port",
        _StaticCalendarEvidencePort,
    )
    market_calendar.load_cn_market_calendar_evidence.cache_clear()


UNSAFE_ROUTE_TOKENS = {
    "approve",
    "batch-delete",
    "cancel",
    "clear",
    "collect",
    "commit",
    "delete",
    "execute",
    "fetch",
    "generate",
    "heartbeat",
    "import",
    "ingest",
    "lease",
    "migrate",
    "publish",
    "recalculate",
    "refresh",
    "reject",
    "repair",
    "replay",
    "reset",
    "resume",
    "revoke",
    "rollback",
    "rotate",
    "run",
    "send",
    "simulate",
    "submitting",
    "sync",
    "toggle",
    "train",
    "trigger",
    "update",
    "upload",
}

EXCLUDED_ROUTE_PREFIXES = {
    "/api/debug/server-logs/stream/",
    "/api/docs/",
    "/api/redoc/",
    "/api/schema/",
}

HTML_FRAGMENT_ROUTES = {
    "/api/dashboard/action-recommendation/",
    "/api/dashboard/attention-items/",
    "/api/dashboard/pulse-card/",
    "/api/dashboard/regime-status/",
    "/api/decision/context/step1/",
    "/api/decision/context/step2/",
    "/api/decision/context/step3/",
    "/api/decision/context/step4/",
    "/api/decision/context/step5/",
    "/api/decision/context/step6/",
}

EMPTY_STATE_REDIRECT_ROUTES = {
    "/api/dashboard/alpha/exit-panel/",
    "/api/dashboard/alpha/factor-panel/",
    "/api/dashboard/alpha/stocks/",
    "/api/dashboard/positions/",
}

GOVERNED_UNAVAILABLE_ROUTES = {
    "/api/data-center/production-coverage/summary/",
    "/api/data-center/production-coverage/universe/",
    "/api/decision-ready/",
    "/api/ready/",
    "/api/realtime/market-summary/",
    "/api/risk-center/research/decision-scorecard/",
    "/api/risk-center/research/market-state/",
    "/api/risk-center/research/strategy-brief/",
    "/api/risk-center/stress-scenario-sets/active/",
    "/api/risk-center/stress-scenario-sets/impact-preview/",
    "/api/sector/rotation/",
    "/api/terminal/runs/",
    "/api/terminal/runs/queue/",
    "/api/tui/operator/governance-queue/",
}


def _walk_patterns(
    patterns: Iterable[URLPattern | URLResolver],
    prefix: str = "",
) -> Iterable[tuple[str, URLPattern]]:
    for item in patterns:
        route = f"{prefix}{item.pattern}"
        if isinstance(item, URLResolver):
            yield from _walk_patterns(item.url_patterns, route)
        else:
            yield route, item


def _supports_get(pattern: URLPattern) -> bool:
    callback: Any = pattern.callback
    actions = getattr(callback, "actions", None)
    if isinstance(actions, dict):
        return "get" in actions
    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class is not None:
        return callable(getattr(view_class, "get", None))
    return True


def _normalize_static_route(route: str) -> str | None:
    normalized = route.lstrip("^/").replace("^", "").rstrip("$")
    if not normalized.startswith("api/"):
        return None
    if any(marker in normalized for marker in ("<", ">", "(?P", "\\.")):
        return None
    path = f"/{normalized}"
    if any(path.startswith(prefix) for prefix in EXCLUDED_ROUTE_PREFIXES):
        return None
    segments = {segment for segment in path.lower().split("/") if segment}
    if segments & UNSAFE_ROUTE_TOKENS:
        return None
    return path


def _static_get_routes() -> list[str]:
    routes: set[str] = set()
    for raw_route, pattern in _walk_patterns(get_resolver().url_patterns):
        route = _normalize_static_route(raw_route)
        if route is not None and _supports_get(pattern):
            routes.add(route)
    return sorted(routes)


STATIC_GET_ROUTES = _static_get_routes()
CALENDAR_WORKBENCH_SCOPE_ROUTE = "/api/data-center/exchange-calendars/workbench/scope/"
REALTIME_MARKET_SUMMARY_ROUTE = "/api/realtime/market-summary/"
STRESS_SCENARIOS_ROUTE = "/api/risk-center/stress-scenarios/"
OWNED_TRANSACTION_ROUTES = {CALENDAR_WORKBENCH_SCOPE_ROUTE}
STATIC_GET_ROUTE_PARAMETERS = tuple(
    pytest.param(
        route,
        marks=pytest.mark.django_db(transaction=route in OWNED_TRANSACTION_ROUTES),
    )
    for route in STATIC_GET_ROUTES
)


@pytest.mark.parametrize("path", STATIC_GET_ROUTE_PARAMETERS)
def test_static_authenticated_get_endpoint_never_returns_5xx(
    admin_client: Client,
    active_decision_runtime: None,
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safe static GET APIs use explicit calendar coverage and never return 5xx."""

    _install_static_calendar_evidence(monkeypatch)
    price_read_calls: list[tuple[str, ...]] = []
    scenario_query_repository: _EmptyScenarioQueryRepository | None = None
    if path == STRESS_SCENARIOS_ROUTE:
        empty_repository = _EmptyScenarioQueryRepository()
        scenario_query_repository = empty_repository
        monkeypatch.setattr(
            scenario_public,
            "get_scenario_query_repository",
            lambda: empty_repository,
        )
    if path == REALTIME_MARKET_SUMMARY_ROUTE:

        def _empty_realtime_price_read(
            use_case: PricePollingUseCase,
            asset_codes: list[str],
        ) -> list[dict[str, Any]]:
            """Supply no index observations at the public read boundary."""
            del use_case
            price_read_calls.append(tuple(asset_codes))
            return []

        monkeypatch.setattr(PricePollingUseCase, "get_latest_prices", _empty_realtime_price_read)
    try:
        response = admin_client.get(path)
    finally:
        market_calendar.load_cn_market_calendar_evidence.cache_clear()
    if path == STRESS_SCENARIOS_ROUTE:
        assert scenario_query_repository is not None, path
        expected_reason = "stress scenario catalog is empty; initialize or configure Risk Center"
        assert response.status_code == 503, path
        assert response.headers.get("Content-Type", "").startswith("application/json"), path
        payload = response.json()
        assert payload["success"] is False, path
        assert payload["data"] is None, path
        assert payload["detail"] == expected_reason, path
        assert payload["blocked_reason"] == expected_reason, path
        assert payload["must_not_use_for_decision"] is True, path
        assert scenario_query_repository.definition_calls == [False], path
        assert scenario_query_repository.current_revision_calls == [(None, False)], path
        return
    if path == CALENDAR_WORKBENCH_SCOPE_ROUTE:
        assert response.status_code == 200, path
        assert response.headers["Content-Type"].startswith("application/json"), path
        payload = response.json()
        data = payload["data"]
        assert payload["success"] is True, path
        assert data["metadata_status"] == "blocked", path
        assert data["metadata"] is None, path
        assert data["blocked_reason"] == "CALENDAR_CAPTURE_DATASET_MISSING", path
        assert data["blocked_reason"] != "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED", path
        assert data["secret_runtime_status"] == "not_checked", path
        assert data["current_pointer_status"] == "not_scoped", path
        return
    if path == REALTIME_MARKET_SUMMARY_ROUTE:
        expected_codes = ("000001.SH", "399001.SZ", "399006.SZ")
        assert price_read_calls == [expected_codes], path
        assert response.status_code == 503, path
        assert response.headers.get("Content-Type", "").startswith("application/json"), path
        payload = response.json()
        assert payload["success"] is False, path
        assert payload["available_index_count"] == 0, path
        assert payload["must_not_use_for_decision"] is True, path
        assert payload["contract"]["must_not_use_for_decision"] is True, path
        assert payload["contract"]["missing_index_codes"] == list(expected_codes), path
        return
    if path in EMPTY_STATE_REDIRECT_ROUTES:
        assert response.status_code == 302, path
        assert response.headers["Location"].startswith("/dashboard/"), path
        return
    if path in HTML_FRAGMENT_ROUTES:
        assert response.status_code == 200, path
        assert response.headers["Content-Type"].startswith("text/html"), path
        return
    if path in GOVERNED_UNAVAILABLE_ROUTES:
        assert response.status_code in {200, 503}
        assert response.headers["Content-Type"].startswith("application/json")
        if response.status_code == 503 and path not in {
            "/api/decision-ready/",
            "/api/ready/",
        }:
            payload = response.json()
            nested_data = payload.get("data")
            nested_contract = payload.get("contract")
            assert payload.get("success") is False or any(
                item.get("must_not_use_for_decision") is True
                for item in (payload, nested_data, nested_contract)
                if isinstance(item, dict)
            ), path
        return

    assert response.status_code < 500, path
    assert response.status_code not in {301, 302, 307, 308}, path
    content_type = response.headers.get("Content-Type", "")
    assert content_type.startswith(
        ("application/json", "text/plain", "text/csv", "application/octet-stream")
    ), (path, response.status_code, content_type)


def test_static_get_inventory_is_broad_and_deterministic() -> None:
    """The contract must cover the broad published read surface."""

    assert len(STATIC_GET_ROUTES) >= 150
    assert len(STATIC_GET_ROUTES) == len(set(STATIC_GET_ROUTES))
    assert "/api/health/" in STATIC_GET_ROUTES
    assert "/api/regime/navigator/" in STATIC_GET_ROUTES
    assert "/api/signal/" in STATIC_GET_ROUTES
    assert "/api/prompt/chat/models" in STATIC_GET_ROUTES
