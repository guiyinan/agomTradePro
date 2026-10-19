"""Authenticated browser journeys for the published equity-pool TUI actions.

The tests exercise the real TUI metadata, executor, owner HTTP endpoint,
Application summary builder, and renderer. Explicit test-only read ports supply
pool membership and publication-gated context; they do not activate providers
or establish production publication qualification.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connection
from django.test import Client
from playwright.sync_api import Locator, Page, Response, Route, expect, sync_playwright

from tests.component.equity import test_research_snapshot_tui_browser as browser_fixtures
from tests.support import account_authority_generation_flush as authority_fixtures
from tests.support.native_postgres_database import assert_native_postgres_test_database

loopback_only_python_network = browser_fixtures.loopback_only_python_network
subprocess_policy = browser_fixtures.subprocess_policy
test_only_runtime_admission = browser_fixtures.test_only_runtime_admission
preserve_account_authority_generation = authority_fixtures.preserve_account_authority_generation

_SOURCE_DATABASE_NAME = str(connection.settings_dict.get("NAME") or "")

SCREEN_KEY = "research.asset-lab"
SUMMARY_ACTION = "equity.pool-summary"
LIST_ACTION = "equity.pool-list"
POOL_ACTIONS = (SUMMARY_ACTION, LIST_ACTION)
POOL_CODES = ("000001.SZ", "000002.SZ")
POOL_ENDPOINT_PATH = "/api/equity/pool/"
EXPECTED_TOP_RESTRICTION = "本次估值发布范围存在缺口；股票池仅供观察，当前结果不可用于决策。"
EXPECTED_ROW_RESTRICTION = (
    "估值资料缺失，暂不用于依赖估值的筛选/计划；仅供观察，当前估值资料不可用于决策。"
)
GLOBAL_BLOCK_REASON = "publication_audit_integrity_failed"
LOCAL_VALUATION_REASON = "valuation_source_data_unavailable"


@dataclass(frozen=True)
class PublishedPoolBrowserCase:
    """One consumer-only fixture outcome for the authenticated browser journey."""

    name: str
    expected_outcome: str
    global_gates: dict[str, dict[str, object]]
    contexts: dict[str, dict[str, object]]
    expected_context_reads: int


@dataclass
class PublishedPoolReadPortEvidence:
    """Calls recorded by the two explicit owner read-port fixtures."""

    case: PublishedPoolBrowserCase
    gate_calls: list[tuple[str, str]]
    context_calls: list[dict[str, object]]


@dataclass
class PublishedPoolBrowserJourney:
    """Authenticated browser session and evidence from two real TUI actions."""

    page: Page
    live_server: Any
    case: PublishedPoolBrowserCase
    ui_keys: dict[str, str]
    browser_requests: list[dict[str, str]]
    nonlocal_browser_attempts: list[str]
    page_errors: list[str]
    request_failures: list[str]
    http_errors: list[dict[str, object]]
    python_socket_attempts: list[str]
    native_database: dict[str, str]
    gate_calls: list[tuple[str, str]]
    context_calls: list[dict[str, object]]
    action_results: list[dict[str, object]]

    def assert_local_browser_path(self) -> None:
        """Require the expected authenticated TUI calls and loopback-only traffic."""
        expected_netloc = urlsplit(self.live_server.url).netloc
        assert expected_netloc
        assert all(
            urlsplit(item["url"]).netloc == expected_netloc for item in self.browser_requests
        )
        assert self.nonlocal_browser_attempts == []
        assert self.python_socket_attempts == []
        assert self.page_errors == []
        assert self.request_failures == []
        action_paths = Counter(
            urlsplit(item["url"]).path
            for item in self.browser_requests
            if item["method"] == "POST"
            and urlsplit(item["url"]).path.startswith("/api/tui/actions/")
        )
        expected_pool_paths = {
            f"/api/tui/actions/{SUMMARY_ACTION}/run/": 1,
            f"/api/tui/actions/{LIST_ACTION}/run/": 1,
        }
        assert {path: action_paths[path] for path in expected_pool_paths} == expected_pool_paths
        expected_readonly_autoloads = {
            "/api/tui/actions/asset-analysis.pool-summary/run/",
            "/api/tui/actions/backtest.summary/run/",
            "/api/tui/actions/backtest.list/run/",
        }
        assert set(action_paths) - set(expected_pool_paths) <= expected_readonly_autoloads
        assert all(
            error["path"] == "/api/tui/operator/governance-queue/" and error["status"] == 503
            for error in self.http_errors
        )
        assert [row["action_key"] for row in self.action_results] == list(POOL_ACTIONS)
        assert len(self.gate_calls) == 4
        assert len(self.context_calls) == self.case.expected_context_reads


def _global_gate(
    case_name: str,
    dataset_key: str,
) -> dict[str, object]:
    """Build one complete test-only global publication identity and coverage."""
    partial_valuation = case_name == "partial" and dataset_key == "equity.valuation.fact"
    is_blocked = case_name == "blocked" and dataset_key == "equity.financial.fact"
    requested = 2
    eligible = 1 if partial_valuation else requested
    selected = 1 if partial_valuation else requested
    missing = 1 if partial_valuation else 0
    gate: dict[str, object] = {
        "dataset_key": dataset_key,
        "publication_key": "current",
        "publication_id": f"test-publication-{dataset_key}",
        "published_at": "2026-10-16T08:00:00+08:00",
        "as_of": "2026-10-16T07:59:00+08:00",
        "policy_identity": "test-equity-policy-v1",
        "policy_version": "test-equity-policy-v1",
        "selected_source": "test-owner-context-port",
        "publication_run_id": f"test-run-{dataset_key}",
        "publication_outcome": "partial" if partial_valuation else "success",
        "coverage_requested_count": requested,
        "coverage_eligible_count": eligible,
        "coverage_selected_count": selected,
        "coverage_missing_count": missing,
        "freshness_status": "fresh",
        "must_not_use_for_decision": is_blocked,
        "blocked_reason": GLOBAL_BLOCK_REASON if is_blocked else None,
    }
    return gate


def _scope_block(asset_code: str, publication_id: str) -> dict[str, object]:
    """Bind the supported local valuation restriction to this test publication."""
    return {
        "asset_code": asset_code,
        "reason_code": LOCAL_VALUATION_REASON,
        "target_trade_date": "2026-10-16",
        "publication_id": publication_id,
        "source": "test-owner-context-port",
        "publication_run_id": "test-run-equity.valuation.fact",
        "policy_version": "test-equity-policy-v1",
        "dataset_key": "equity.valuation.fact",
        "publication_key": "current",
    }


def _asset_gate(
    global_gate: Mapping[str, object],
    asset_code: str,
    *,
    blocked: bool = False,
) -> dict[str, object]:
    """Copy global identity into one canonical master-asset gate."""
    gate = dict(global_gate)
    gate["asset_code"] = asset_code
    gate["must_not_use_for_decision"] = blocked
    gate["blocked_reason"] = LOCAL_VALUATION_REASON if blocked else None
    if blocked:
        gate["scope_block"] = _scope_block(
            asset_code,
            str(global_gate["publication_id"]),
        )
    return gate


def _context_row(
    code: str,
    financial_global: Mapping[str, object],
    valuation_global: Mapping[str, object],
    *,
    valuation_blocked: bool,
) -> dict[str, object]:
    """Return a resolved owner-context row with honest source clocks."""
    name = "测试银行" if code == POOL_CODES[0] else "测试制造"
    valuation_gate = _asset_gate(
        valuation_global,
        code,
        blocked=valuation_blocked,
    )
    return {
        "requested_code": code,
        "asset_code": code,
        "name": name,
        "sector": "银行" if code == POOL_CODES[0] else "制造",
        "must_not_use_for_decision": valuation_blocked,
        "blocked_reason": LOCAL_VALUATION_REASON if valuation_blocked else None,
        "publication_gates": {
            "financial": _asset_gate(financial_global, code),
            "valuation": valuation_gate,
        },
        "roe": 12.5 if code == POOL_CODES[0] else 10.0,
        "pe": 7.2 if valuation_blocked or code == POOL_CODES[0] else 10.8,
        "pb": 0.8,
        "revenue_growth": 8.0,
        "profit_growth": 6.0,
        "source_times": {
            "financial": {
                "roe": {
                    "observed_at": "2026-10-16T07:30:00+08:00",
                    "available_at": "2026-10-16T07:45:00+08:00",
                    "fetched_at": "2026-10-16T07:46:00+08:00",
                },
                "debt_ratio": {
                    "observed_at": None,
                    "available_at": None,
                    "fetched_at": "2026-10-16T07:46:00+08:00",
                },
            },
            "valuation": {
                "val_date": "2026-10-16",
                "observed_at": None if valuation_blocked else "2026-10-16T07:30:00+08:00",
                "available_at": None if valuation_blocked else "2026-10-16T07:45:00+08:00",
                "fetched_at": "2026-10-16T07:46:00+08:00",
            },
        },
    }


def _case_payload(name: str) -> PublishedPoolBrowserCase:
    """Create one partial, complete, or globally blocked consumer fixture."""
    assert name in {"partial", "full", "blocked"}
    financial_global = _global_gate(name, "equity.financial.fact")
    valuation_global = _global_gate(name, "equity.valuation.fact")
    valuation_blocked = name == "partial"
    contexts = {
        code: _context_row(
            code,
            financial_global,
            valuation_global,
            valuation_blocked=valuation_blocked and code == POOL_CODES[0],
        )
        for code in POOL_CODES
    }
    return PublishedPoolBrowserCase(
        name=name,
        expected_outcome={"partial": "partial", "full": "success", "blocked": "blocked"}[name],
        global_gates={
            "equity.financial.fact": financial_global,
            "equity.valuation.fact": valuation_global,
        },
        contexts=contexts,
        expected_context_reads=0 if name == "blocked" else 2,
    )


@pytest.fixture
def published_pool_case(request: pytest.FixtureRequest) -> PublishedPoolBrowserCase:
    """Select one explicit consumer fixture without changing runtime qualification."""
    value = request.param
    assert isinstance(value, str)
    return _case_payload(value)


@pytest.fixture
def published_pool_read_ports(
    monkeypatch: pytest.MonkeyPatch,
    published_pool_case: PublishedPoolBrowserCase,
) -> PublishedPoolReadPortEvidence:
    """Replace only pool persistence and Data Center read ports for owner HTTP calls."""
    import apps.equity.infrastructure.adapters as equity_adapters
    import apps.equity.interface.pool_actions as pool_actions

    gate_calls: list[tuple[str, str]] = []
    context_calls: list[dict[str, object]] = []

    def gate_reader(dataset_key: str, publication_key: str) -> dict[str, object]:
        """Supply the named local publication fixture at the owner read boundary."""
        gate_calls.append((dataset_key, publication_key))
        assert publication_key == "current"
        return dict(published_pool_case.global_gates[dataset_key])

    def context_reader(
        stock_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
    ) -> dict[str, dict[str, object]]:
        """Supply resolved rows only to the existing Application consumer port."""
        context_calls.append(
            {
                "stock_codes": list(stock_codes),
                "publication_key": publication_key,
                "include_price": include_price,
            }
        )
        assert stock_codes == list(POOL_CODES)
        assert publication_key == "current"
        assert include_price is False
        return {code: dict(row) for code, row in published_pool_case.contexts.items()}

    monkeypatch.setattr(
        equity_adapters.StockPoolRepositoryAdapter,
        "get_current_pool",
        lambda _repository: list(POOL_CODES),
    )
    monkeypatch.setattr(
        equity_adapters.StockPoolRepositoryAdapter,
        "get_latest_pool_info",
        lambda _repository: {
            "regime": "测试市场环境",
            "updated_at": "2026-10-16T08:00:00+08:00",
        },
    )
    monkeypatch.setattr(pool_actions, "get_decision_publication_gate", gate_reader)
    monkeypatch.setattr(pool_actions, "get_published_stock_context_map", context_reader)
    return PublishedPoolReadPortEvidence(
        case=published_pool_case,
        gate_calls=gate_calls,
        context_calls=context_calls,
    )


@pytest.fixture
def published_pool_browser_journey(
    live_server: Any,
    django_user_model: Any,
    published_pool_read_ports: PublishedPoolReadPortEvidence,
    test_only_runtime_admission: None,
    subprocess_policy: None,
    loopback_only_python_network: list[str],
) -> Any:
    """Open the real authenticated pool screen behind two local-network fences."""
    assert not str(os.environ.get("DJANGO_SETTINGS_MODULE", "")).endswith(".production")
    assert connection.alias == "default"
    if connection.vendor == "postgresql":
        test_database_name = assert_native_postgres_test_database()
    else:
        assert connection.vendor == "sqlite"
        test_database_name = str(connection.settings_dict.get("NAME") or "")
        assert test_database_name
        memory_database = test_database_name == ":memory:" or (
            test_database_name.startswith("file:") and "mode=memory" in test_database_name
        )
        if not memory_database:
            test_settings = connection.settings_dict.get("TEST")
            assert isinstance(test_settings, dict)
            configured_test_name = test_settings.get("NAME")
            assert isinstance(configured_test_name, str) and configured_test_name
            assert Path(test_database_name).resolve() == Path(configured_test_name).resolve()
            assert Path(test_database_name).resolve() != Path(_SOURCE_DATABASE_NAME).resolve()
    native_database = {
        "vendor": connection.vendor,
        "alias": connection.alias,
        "host": str(connection.settings_dict.get("HOST")),
        "port": str(connection.settings_dict.get("PORT")),
        "test_name": test_database_name,
    }
    owner = django_user_model.objects.create_user(
        username=f"pool-browser-{uuid4().hex[:12]}",
        password="local-pool-browser-test-only",
        is_staff=False,
    )
    client = Client()
    client.force_login(owner)
    cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    requests: list[dict[str, str]] = []
    browser_attempts: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    http_errors: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": cookie,
                    "url": live_server.url,
                }
            ]
        )

        def enforce_local_origin(route: Route) -> None:
            """Abort nonlocal browser requests before Chromium starts transport."""
            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", enforce_local_origin)
        page = context.new_page()
        page.on(
            "request",
            lambda browser_request: requests.append(
                {"method": browser_request.method, "url": browser_request.url}
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: (
                http_errors.append({"path": urlsplit(response.url).path, "status": response.status})
                if response.status >= 400
                else None
            ),
        )
        page.on(
            "requestfailed",
            lambda browser_request: request_failures.append(
                f"{browser_request.method} {browser_request.url}: {browser_request.failure}"
            ),
        )
        run = PublishedPoolBrowserJourney(
            page=page,
            live_server=live_server,
            case=published_pool_read_ports.case,
            ui_keys={},
            browser_requests=requests,
            nonlocal_browser_attempts=browser_attempts,
            page_errors=page_errors,
            request_failures=request_failures,
            http_errors=http_errors,
            python_socket_attempts=loopback_only_python_network,
            native_database=native_database,
            gate_calls=published_pool_read_ports.gate_calls,
            context_calls=published_pool_read_ports.context_calls,
            action_results=[],
        )
        try:
            page.goto(f"{live_server.url}/tui/?screen={SCREEN_KEY}", wait_until="networkidle")
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            expect(page.locator('[data-experience-mode="professional"]')).to_have_attribute(
                "aria-selected", "true"
            )
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()
            run.ui_keys = _screen_action_ui_keys(page)
            yield run
        finally:
            evidence = (
                Path(settings.BASE_DIR)
                / ".tmp/ash04-published-pool-browser-evidence"
                / f"{run.case.name}-{uuid4().hex[:12]}"
            )
            evidence.mkdir(parents=True, exist_ok=False)
            screenshot_path = evidence / "viewport.png"
            if not page.is_closed():
                page.screenshot(path=str(screenshot_path), full_page=False)
            evidence_payload: dict[str, object] = {
                "case": run.case.name,
                "screen_key": SCREEN_KEY,
                "action_ui_keys_from_authenticated_metadata": run.ui_keys,
                "production_activation": False,
                "consumer_fixture_only": True,
                "provider_qualification": False,
                "native_test_database": native_database,
                "global_gate_reads": run.gate_calls,
                "owner_context_reads": run.context_calls,
                "action_results": run.action_results,
                "browser_requests": requests,
                "nonlocal_browser_attempts": browser_attempts,
                "nonlocal_python_socket_attempts": loopback_only_python_network,
                "request_failures": request_failures,
                "http_error_responses": http_errors,
                "expected_auxiliary_unavailability": "Governance queue can return503 in the isolated fixture without calendar/audit admission; this is recorded and never considered source readiness.",
                "page_errors": page_errors,
                "screenshot": str(screenshot_path),
            }
            (evidence / "journey.json").write_text(
                json.dumps(evidence_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            context.close()
            browser.close()
            assert loopback_only_python_network == []


def _screen_action_ui_keys(page: Page) -> dict[str, str]:
    """Resolve actual action UI identifiers without deriving metadata digests."""
    result = page.evaluate(
        """async (screenKey) => {
            const response = await fetch(`/api/tui/screens/${encodeURIComponent(screenKey)}/`, {
                credentials: "same-origin",
                headers: {"Accept": "application/json"},
            });
            const payload = await response.json();
            return {status: response.status, contentType: response.headers.get("content-type"), payload};
        }""",
        SCREEN_KEY,
    )
    return _find_action_ui_keys(result)


def _find_action_ui_keys(screen_result: object) -> dict[str, str]:
    """Validate the fetched screen metadata and select only the two pool actions."""
    assert isinstance(screen_result, dict)
    assert screen_result.get("status") == 200
    assert str(screen_result.get("contentType") or "").split(";", 1)[0] == "application/json"
    payload = screen_result.get("payload")
    assert isinstance(payload, dict)
    actions = payload.get("actions")
    assert isinstance(actions, list)
    selected: dict[str, str] = {}
    for value in actions:
        if not isinstance(value, dict):
            continue
        key = value.get("key")
        ui_key = value.get("ui_key")
        if key in POOL_ACTIONS:
            assert isinstance(ui_key, str) and ui_key
            selected[str(key)] = ui_key
    assert set(selected) == set(POOL_ACTIONS)
    return selected


def _action_form(page: Page, ui_key: str) -> Any:
    """Find a real rendered metadata action form and expand its task group."""
    forms = page.locator("[data-actions-panel] form[data-action-ui-key]")
    form = None
    for index in range(forms.count()):
        candidate = forms.nth(index)
        if candidate.get_attribute("data-action-ui-key") == ui_key:
            form = candidate
            break
    assert form is not None
    if not form.is_visible():
        disclosure = form.locator("xpath=ancestor::details[1]")
        if disclosure.count() == 1 and disclosure.get_attribute("open") is None:
            disclosure.locator(":scope > summary").click()
    expect(form).to_be_visible()
    return form


def _run_pool_action(
    journey: PublishedPoolBrowserJourney,
    action_key: str,
) -> tuple[Response, dict[str, Any]]:
    """Submit one visible metadata-backed pool action to the real TUI endpoint."""
    page = journey.page
    actions_panel = page.locator("[data-actions-panel]")
    if not actions_panel.is_visible():
        page.keyboard.press("F9")
    expect(actions_panel).to_be_visible()
    form = _action_form(page, journey.ui_keys[action_key])
    submit = form.locator(".tui-action-submit")
    expect(submit).to_have_count(1)
    action_path = f"/api/tui/actions/{action_key}/run/"
    with page.expect_response(
        lambda response: urlsplit(response.url).path == action_path
    ) as response_info:
        submit.click()
    response = response_info.value
    assert urlsplit(response.url).netloc == urlsplit(journey.live_server.url).netloc
    assert response.request.method == "POST"
    assert response.status == 200
    assert response.headers.get("content-type", "").split(";", 1)[0] == "application/json"
    result = response.json()
    assert isinstance(result, dict)
    assert result["action"]["key"] == action_key
    assert result["action"]["ui_key"] == journey.ui_keys[action_key]
    assert result["response"]["status_code"] == 200
    assert result["debug"] == {"raw_available": False, "raw_response": None}
    view_model = result["view_model"]
    assert isinstance(view_model, dict)
    journey.action_results.append(
        {
            "action_key": action_key,
            "http_status": response.status,
            "owner_status": result["response"]["status_code"],
            "outcome": result["outcome"],
            "view_kind": view_model.get("kind"),
        }
    )
    return response, result


def _field_values(view_model: Mapping[str, object]) -> dict[str, str]:
    """Index only display fields from a detail view model."""
    fields = view_model.get("fields")
    assert isinstance(fields, list)
    indexed: dict[str, str] = {}
    for value in fields:
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            field_value = value.get("value")
            assert isinstance(field_value, str)
            indexed[str(value["key"])] = field_value
    return indexed


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize(
    "published_pool_case",
    ("partial", "full", "blocked"),
    indirect=True,
)
def test_published_pool_screen_preserves_partial_full_and_blocked_outcomes(
    published_pool_case: PublishedPoolBrowserCase,
    published_pool_browser_journey: PublishedPoolBrowserJourney,
) -> None:
    """The real TUI keeps the complete pool and communicates each read outcome."""
    journey = published_pool_browser_journey
    assert journey.case == published_pool_case

    _summary_response, summary_result = _run_pool_action(journey, SUMMARY_ACTION)
    summary_view = summary_result["view_model"]
    assert isinstance(summary_view, dict)
    assert summary_view["kind"] == "detail"
    assert summary_result["outcome"] == published_pool_case.expected_outcome
    assert summary_view["outcome"] == published_pool_case.expected_outcome
    summary_fields = _field_values(summary_view)
    main_panel = journey.page.locator("[data-main-panel]")
    expect(main_panel).to_be_visible()

    if published_pool_case.name == "partial":
        assert summary_view["must_not_use_for_decision"] is True
        assert summary_fields["requested_count"] == "2"
        assert summary_fields["blocked_count"] == "1"
        assert summary_fields["restriction_message"] == EXPECTED_TOP_RESTRICTION
        expect(main_panel).to_contain_text("股票池仅供观察")
        expect(main_panel).to_contain_text("当前结果不可用于决策")
        expect(main_panel).to_contain_text("本次请求股票数")
        expect(main_panel).to_contain_text("估值资料受限股票数")
        _assert_visible_in_viewport(
            journey.page, main_panel.locator("dd").filter(has_text="股票池仅供观察")
        )

    elif published_pool_case.name == "full":
        assert summary_view["must_not_use_for_decision"] is False
        assert summary_fields["requested_count"] == "2"
        assert summary_fields["blocked_count"] == "0"
        assert summary_fields["restriction_message"] == "-"
        expect(main_panel).not_to_contain_text("仅供观察")
        expect(main_panel).to_contain_text("股票池资料已发布")
        expect(main_panel).not_to_contain_text("published")
        expect(main_panel).not_to_contain_text("outcome")
        _assert_visible_in_viewport(journey.page, main_panel.get_by_text("本次请求股票数"))

    else:
        assert summary_view["must_not_use_for_decision"] is True
        assert summary_fields["blocked_count"] == "未提供"
        expect(main_panel).to_contain_text("当前股票池资料不可用")
        expect(main_panel).not_to_contain_text(GLOBAL_BLOCK_REASON)
        _assert_visible_in_viewport(
            journey.page, main_panel.locator("dd").filter(has_text="当前股票池资料不可用")
        )

    summary_evidence = Path(settings.BASE_DIR) / ".tmp/ash04-published-pool-browser-evidence"
    summary_evidence.mkdir(parents=True, exist_ok=True)
    summary_screenshot = summary_evidence / f"{journey.case.name}-summary-{uuid4().hex[:12]}.png"
    journey.page.screenshot(path=str(summary_screenshot), full_page=False)
    journey.action_results[-1]["viewport_screenshot"] = str(summary_screenshot)

    _list_response, list_result = _run_pool_action(journey, LIST_ACTION)
    list_view = list_result["view_model"]
    assert isinstance(list_view, dict)
    assert list_view["kind"] == "datagrid"
    assert list_result["outcome"] == published_pool_case.expected_outcome
    assert list_view["outcome"] == published_pool_case.expected_outcome

    if published_pool_case.name in {"partial", "full"}:
        rows = list_view["rows"]
        assert isinstance(rows, list) and len(rows) == 2
        assert [
            str(row["code"]).startswith(code) for row, code in zip(rows, POOL_CODES, strict=True)
        ] == [
            True,
            True,
        ]
        table = main_panel.locator(".tui-datagrid table")
        expect(table).to_be_visible()
        body_rows = table.locator("tbody tr")
        expect(body_rows).to_have_count(2)
        if published_pool_case.name == "partial":
            assert rows[0]["status_label"] == "估值资料受限"
            assert rows[1]["status_label"] == "资料已发布"
            assert rows[0]["restriction_message"] == EXPECTED_ROW_RESTRICTION
            assert rows[1]["restriction_message"] in {"", "-"}
            expect(body_rows.nth(0)).to_contain_text("估值资料受限")
            expect(body_rows.nth(0)).to_contain_text("仅供观察")
            expect(body_rows.nth(1)).to_contain_text("资料已发布")
            expect(body_rows.nth(1)).not_to_contain_text("估值资料缺失")
            expect(main_panel).not_to_contain_text(LOCAL_VALUATION_REASON)
            _assert_visible_in_viewport(journey.page, body_rows.nth(0))
        else:
            assert all(row["status_label"] == "资料已发布" for row in rows)
            assert all(row["restriction_message"] in {"", "-"} for row in rows)
            expect(table).not_to_contain_text("仅供观察")
            _assert_visible_in_viewport(journey.page, body_rows.nth(0))
    else:
        assert list_view["rows"] == []
        assert isinstance(list_view.get("empty_message"), str)
        assert "不可用" in str(list_view["empty_message"])
        expect(main_panel).to_contain_text(str(list_view["empty_message"]))
        expect(main_panel).not_to_contain_text("暂无可显示数据")
        expect(main_panel).not_to_contain_text(GLOBAL_BLOCK_REASON)

    assert len(journey.context_calls) == published_pool_case.expected_context_reads
    journey.assert_local_browser_path()


def _assert_visible_in_viewport(page: Page, locator: Locator) -> None:
    """Keep the primary outcome warning visible in the captured first viewport."""
    expect(locator).to_be_visible()
    bounds = locator.bounding_box()
    assert bounds is not None
    viewport_height = page.evaluate("window.innerHeight")
    assert isinstance(viewport_height, (int, float))
    assert bounds["y"] >= 0
    assert bounds["y"] + bounds["height"] <= viewport_height
