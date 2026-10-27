"""Private local browser journey for M1 temporary-target previews.

This candidate uses synthetic typed source fixtures and a Playwright-to-Django
Client transport. It is local development evidence only; it is not live HTTP or
production M1 acceptance evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.db import connections
from django.db.models import Model
from django.http.cookie import parse_cookie
from django.test import Client
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Request,
    Response,
    Route,
    sync_playwright,
)
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import DailyInspectionReportModel
from apps.strategy.infrastructure.models import PositionManagementRuleModel, StrategyModel
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor
from tests.integration.simulated_trading import test_readonly_rebalance_plan_owner_api as owner_case
from tests.integration.simulated_trading.test_m1_published_close_browser_journey import (
    isolated_m1_revision_table as isolated_m1_revision_table,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

ACTION_KEY = "account-inspection.run"
SCREEN_KEY = "task.account-inspection"
DASHBOARD_PANEL_KEY = "account-inspection-run"
ACTION_URL = f"/api/tui/actions/{ACTION_KEY}/run/"
SYNTHETIC_EVIDENCE_KIND = "local_synthetic_fixture_api_transport_development_evidence"
TARGET_TEXT = "600000.SH,0\n000001.SZ,40.330001"
EXPECTED_TARGET_WEIGHTS = {"600000.SH": "0", "000001.SZ": "0.40330001"}
EXPECTED_CASH_REMAINDER = "0.59669999"
EXPECTED_RISK_VALUES: dict[str, str] = {
    "account_max_position_pct": "61",
    "account_max_total_position_pct": "92",
    "account_stop_loss_pct": "11.5",
    "strategy_max_position_pct": "70",
    "strategy_max_total_position_pct": "94",
    "strategy_stop_loss_pct": "13.5",
}


class _ObservedExecutor:
    """Record the real same-process owner call while delegating unchanged."""

    def __init__(
        self,
        delegate: TuiInternalActionExecutor,
        owner_calls: list[dict[str, Any]],
    ) -> None:
        self._delegate = delegate
        self._owner_calls = owner_calls

    def execute(
        self,
        *,
        method: str,
        endpoint: str,
        params: dict[str, Any],
        body: dict[str, Any],
        user: Any,
        session: Any | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        result = self._delegate.execute(
            method=method,
            endpoint=endpoint,
            params=params,
            body=body,
            user=user,
            session=session,
            idempotency_key=idempotency_key,
        )
        if "/inspections/run/" in endpoint:
            self._owner_calls.append(
                {
                    "method": method,
                    "endpoint": endpoint,
                    "params": dict(params),
                    "body": dict(body),
                    "idempotency_key_sha256": (
                        hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
                        if idempotency_key is not None
                        else None
                    ),
                    "status_code": result.get("status_code"),
                    "payload": result.get("payload"),
                }
            )
        return result


def _playwright_cookies(client: Client, *, host: str) -> list[dict[str, Any]]:
    """Copy the ordinary Django browser-session cookies into Chromium."""

    cookies: list[dict[str, Any]] = []
    for name, morsel in client.cookies.items():
        cookie: dict[str, Any] = {
            "name": name,
            "value": morsel.value,
            "domain": host,
            "path": morsel["path"] or "/",
            "httpOnly": bool(morsel["httponly"]),
            "secure": bool(morsel["secure"]),
        }
        same_site = morsel["samesite"]
        if same_site in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = same_site
        cookies.append(cookie)
    return cookies


def _safe_tui_identifier(value: object) -> str | None:
    """Keep only bounded ASCII identifiers in local browser diagnostics."""

    if not isinstance(value, str):
        return None
    if value == "":
        return ""
    if (
        len(value) > 200
        or not value.isascii()
        or not value[0].isalnum()
        or not all(character.isalnum() or character in "._-" for character in value)
    ):
        return None
    return value


def _safe_tui_query(query: str) -> str:
    """Retain only the public screen/action deep-link identifiers."""

    try:
        pairs = parse_qsl(query, keep_blank_values=False, max_num_fields=20)
    except ValueError:
        return ""
    safe_values: dict[str, str] = {}
    for key, value in pairs:
        if key not in {"screen", "action"} or key in safe_values:
            continue
        safe_value = _safe_tui_identifier(value)
        if safe_value:
            safe_values[key] = safe_value
    return urlencode(
        [(key, safe_values[key]) for key in ("screen", "action") if key in safe_values]
    )


def _safe_browser_location(url: str) -> str:
    """Keep origin, path, and only known screen/action query values."""

    parsed = urlsplit(url)
    safe_query = _safe_tui_query(parsed.query)
    query_suffix = f"?{safe_query}" if safe_query else ""
    if not parsed.scheme and not parsed.netloc:
        return f"{parsed.path or '/'}{query_suffix}"
    if parsed.scheme not in {"http", "https"}:
        return f"{parsed.scheme}:<non-http>"
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    authority = f"{hostname}:{port}" if port is not None else hostname
    return f"{parsed.scheme}://{authority}{parsed.path or '/'}{query_suffix}"


def _safe_bootstrap_observation(status_code: int, response_body: bytes) -> dict[str, Any]:
    """Extract only the public bootstrap contract and screen/action identifiers."""

    observation: dict[str, Any] = {"status": status_code, "payload_is_object": False}
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return observation
    if not isinstance(payload, dict):
        return observation
    observation["payload_is_object"] = True
    observation["contract"] = (
        "tui-bootstrap.v1" if payload.get("contract") == "tui-bootstrap.v1" else None
    )
    observation["requested_screen"] = _safe_tui_identifier(payload.get("requested_screen"))
    observation["resolved_screen"] = _safe_tui_identifier(payload.get("resolved_screen"))
    screen_payload = payload.get("screen")
    screen = screen_payload.get("screen") if isinstance(screen_payload, dict) else None
    observation["screen_key"] = (
        _safe_tui_identifier(screen.get("key")) if isinstance(screen, dict) else None
    )
    dashboard_panels = screen.get("dashboard_panels") if isinstance(screen, dict) else None
    observation["dashboard_panels"] = (
        [
            {"key": panel_key, "action_key": _safe_tui_identifier(panel.get("action_key"))}
            for panel in dashboard_panels[:100]
            if isinstance(panel, dict) and (panel_key := _safe_tui_identifier(panel.get("key")))
        ]
        if isinstance(dashboard_panels, list)
        else None
    )
    actions = screen_payload.get("actions") if isinstance(screen_payload, dict) else None
    observation["action_keys"] = (
        [
            safe_key
            for action in actions[:100]
            if isinstance(action, dict) and (safe_key := _safe_tui_identifier(action.get("key")))
        ]
        if isinstance(actions, list)
        else None
    )
    return observation


def _save_failure_diagnostics(
    *,
    repository_root: Path,
    failure_type: str,
    current_page_url: str,
    pre_browser_client_response: dict[str, str | int | bool],
    browser_requests: list[dict[str, str | int | bool]],
    browser_responses: list[dict[str, str | int]],
    browser_redirects: list[dict[str, str]],
    failed_requests: list[dict[str, str]],
    route_dispatches: list[dict[str, str | int | bool]],
    bootstrap_observations: list[dict[str, Any]],
    page_errors: list[str],
    page: Page,
    safe_observations: dict[str, object],
    first_viewport_screenshot: bytes | None,
) -> Path:
    """Write bounded failure diagnostics and a browser screenshot without secrets."""

    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    run_directory = (
        repository_root
        / ".tmp"
        / "m1-temporary-target-browser-preparation-r2"
        / "runs"
        / f"failure-{run_key}"
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    if first_viewport_screenshot is not None:
        (run_directory / "positive-first-viewport.png").write_bytes(first_viewport_screenshot)
    page_ui_state: dict[str, Any]
    try:
        raw_page_ui_state = page.evaluate(
            """panelKey => ({
                document_title: document.title || "",
                screen_title: document.querySelector("[data-screen-title]")?.textContent?.trim() || "",
                action_form_keys: Array.from(document.querySelectorAll(
                    "[data-actions-panel] form[data-action-ui-key]"
                )).map(form => form.getAttribute("data-action-ui-key") || "").slice(0, 100),
                dashboard_action_forms: Array.from(document.querySelectorAll(
                    `[data-main-panel] [data-dashboard-panel="${CSS.escape(panelKey)}"] form[data-action-ui-key]`
                )).map(form => ({
                    panel_key: form.closest("[data-dashboard-panel]")?.getAttribute("data-dashboard-panel") || "",
                    ui_key: form.getAttribute("data-action-ui-key") || "",
                    visible: !form.hidden && form.getClientRects().length > 0
                        && getComputedStyle(form).visibility !== "hidden"
                })).slice(0, 100)
            })""",
            DASHBOARD_PANEL_KEY,
        )
    except Exception as capture_error:
        page_ui_state = {"capture_error_type": type(capture_error).__name__}
    else:
        page_ui_state = {}
        if isinstance(raw_page_ui_state, dict):
            for key in ("document_title", "screen_title"):
                value = raw_page_ui_state.get(key)
                if isinstance(value, str):
                    page_ui_state[key] = value[:200]
            form_keys = raw_page_ui_state.get("action_form_keys")
            if isinstance(form_keys, list):
                page_ui_state["action_form_keys"] = [
                    safe_key
                    for value in form_keys[:100]
                    if (safe_key := _safe_tui_identifier(value))
                ]
            dashboard_forms = raw_page_ui_state.get("dashboard_action_forms")
            if isinstance(dashboard_forms, list):
                safe_forms: list[dict[str, str | bool]] = []
                for form in dashboard_forms[:100]:
                    if not isinstance(form, dict):
                        continue
                    panel_key = _safe_tui_identifier(form.get("panel_key"))
                    ui_key = _safe_tui_identifier(form.get("ui_key"))
                    visible = form.get("visible")
                    if panel_key is not None and ui_key is not None and isinstance(visible, bool):
                        safe_forms.append(
                            {"panel_key": panel_key, "ui_key": ui_key, "visible": visible}
                        )
                page_ui_state["dashboard_action_forms"] = safe_forms
    screenshot_name: str | None = None
    screenshot_error_type: str | None = None
    try:
        page.screenshot(
            path=str(run_directory / "failure-page.png"),
            full_page=False,
            animations="disabled",
        )
        screenshot_name = "failure-page.png"
    except Exception as screenshot_error:
        screenshot_error_type = type(screenshot_error).__name__
    diagnostics = {
        "evidence_kind": SYNTHETIC_EVIDENCE_KIND,
        "production_m1_acceptance": False,
        "capture_policy": (
            "No HTML, request/response headers, cookies, or request bodies are stored. "
            "URL queries retain only bounded screen/action identifiers; bootstrap and UI "
            "observations retain only contract, screen/action keys, titles, dashboard panel/form "
            "keys, and form visibility flags."
        ),
        "failure_type": failure_type,
        "current_page_url": _safe_browser_location(current_page_url),
        "pre_browser_client_response": pre_browser_client_response,
        "browser_requests": browser_requests,
        "browser_responses": browser_responses,
        "browser_redirects": browser_redirects,
        "failed_requests": failed_requests,
        "route_dispatches": route_dispatches,
        "bootstrap_observations": bootstrap_observations,
        "page_ui_state": page_ui_state,
        "failure_screenshot": screenshot_name,
        "screenshot_error_type": screenshot_error_type,
        "page_errors": page_errors,
        "safe_observations": safe_observations,
    }
    path = run_directory / "failure-diagnostics.json"
    path.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _dispatch_browser_request(
    route: Route,
    *,
    client: Client,
    host: str,
    browser_requests: list[dict[str, Any]],
    route_dispatches: list[dict[str, str | int | bool]],
    bootstrap_observations: list[dict[str, Any]],
    browser_idempotency_keys: list[str],
    browser_csrf_tokens: list[str],
) -> None:
    """Serve one browser request through Django or the existing static finders."""

    request = route.request
    parsed = urlsplit(request.url)
    safe_url = _safe_browser_location(request.url)
    browser_cookie_header = request.headers.get("cookie")
    browser_session_cookie_present = settings.SESSION_COOKIE_NAME in parse_cookie(
        browser_cookie_header or ""
    )
    client_session_cookie_present_before = settings.SESSION_COOKIE_NAME in client.cookies
    route_dispatches.append(
        {
            "event": "route_enter",
            "url": safe_url,
            "method": request.method,
            "browser_session_cookie_present": browser_session_cookie_present,
            "client_session_cookie_present_before": client_session_cookie_present_before,
        }
    )
    if parsed.netloc != host or parsed.scheme != "http":
        route_dispatches.append(
            {"event": "route_aborted", "url": safe_url, "reason": "host_or_scheme_guard"}
        )
        route.abort("blockedbyclient")
        return
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    request_body: dict[str, Any] | None = None
    content_type = request.headers.get("content-type", "")
    raw_body = request.post_data_buffer or b""
    if browser_cookie_header:
        client.cookies.load(browser_cookie_header)
    client_session_cookie_present_after = settings.SESSION_COOKIE_NAME in client.cookies
    if content_type.split(";", maxsplit=1)[0] == "application/json" and raw_body:
        decoded = json.loads(raw_body.decode("utf-8"))
        request_body = decoded if isinstance(decoded, dict) else None
    browser_requests.append(
        {
            "method": request.method,
            "path": path,
            "json_body": request_body,
            "idempotency_key_sha256": (
                hashlib.sha256(request.headers["idempotency-key"].encode("utf-8")).hexdigest()
                if request.headers.get("idempotency-key")
                else None
            ),
        }
    )
    if parsed.path == ACTION_URL and request.method == "POST":
        browser_idempotency_keys.append(request.headers.get("idempotency-key", ""))
        browser_csrf_tokens.append(request.headers.get("x-csrftoken", ""))

    if parsed.path.startswith("/static/"):
        relative_path = parsed.path.removeprefix("/static/")
        static_path = finders.find(relative_path)
        if not isinstance(static_path, str):
            route_dispatches.append(
                {"event": "static_asset_missing", "url": safe_url, "status": 404}
            )
            raise AssertionError(f"TUI static asset is missing: {relative_path}")
        route_dispatches.append({"event": "static_asset_found", "url": safe_url, "status": 200})
        route.fulfill(
            status=200,
            path=static_path,
            content_type=mimetypes.guess_type(static_path)[0] or "application/octet-stream",
        )
        route_dispatches.append({"event": "route_fulfilled", "url": safe_url, "status": 200})
        return

    extra: dict[str, str] = {"HTTP_HOST": host}
    for browser_header, django_header in (
        ("accept", "HTTP_ACCEPT"),
        ("origin", "HTTP_ORIGIN"),
        ("referer", "HTTP_REFERER"),
        ("x-csrftoken", "HTTP_X_CSRFTOKEN"),
        ("x-requested-with", "HTTP_X_REQUESTED_WITH"),
        ("idempotency-key", "HTTP_IDEMPOTENCY_KEY"),
    ):
        value = request.headers.get(browser_header)
        if value:
            extra[django_header] = value
    route_dispatches.append(
        {
            "event": "django_request_start",
            "url": safe_url,
            "method": request.method,
            "client_session_cookie_present": client_session_cookie_present_after,
        }
    )
    response = client.generic(
        request.method,
        path,
        data=raw_body,
        content_type=content_type or None,
        **extra,
    )
    connections.close_all()
    if parsed.path == "/api/tui/bootstrap/":
        bootstrap_observations.append(
            _safe_bootstrap_observation(response.status_code, bytes(response.content))
        )
    response_event: dict[str, str | int | bool] = {
        "event": "django_response",
        "url": safe_url,
        "method": request.method,
        "status": response.status_code,
        "client_session_cookie_present": settings.SESSION_COOKIE_NAME in client.cookies,
    }
    location = response.get("Location")
    if location:
        response_event["location"] = _safe_browser_location(location)
        response_event["redirects_to_login"] = (
            response.status_code in {301, 302, 303, 307, 308}
            and urlsplit(location).path == "/account/login/"
        )
    route_dispatches.append(response_event)
    headers = {
        key.lower(): value
        for key, value in response.items()
        if key.lower() not in {"content-length", "transfer-encoding", "connection"}
    }
    route.fulfill(status=response.status_code, headers=headers, body=bytes(response.content))
    route_dispatches.append(
        {"event": "route_fulfilled", "url": safe_url, "status": response.status_code}
    )


def _field_map(fields: object) -> dict[str, dict[str, str]]:
    """Index a real projected field list by its stable key."""

    assert isinstance(fields, list)
    return {
        str(field["key"]): field
        for field in fields
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }


def _assert_primary_fields_in_first_viewport(
    page: Page,
    view_model: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Assert six P0 result facts are visible with their projected values."""

    expected_labels = {
        "reference_price_basis": "参考价格口径",
        "p0_scope_time": "用途与时点",
        "p0_target_cash": "目标与未分配现金",
        "p0_fees_cash": "费用与现金估算",
        "p0_first_asset": "首项标的建议",
        "p0_applicable_limits": "适用限制",
    }
    raw_fields = view_model.get("fields")
    assert isinstance(raw_fields, list)
    assert all(isinstance(field, dict) for field in raw_fields)
    assert [field["key"] for field in raw_fields[:6]] == list(expected_labels)
    assert [field["key"] for field in raw_fields[6:]] == [
        "report_id",
        "inspection_date",
        "as_of",
        "plan_status",
        "submission",
        "currency",
        "risk_falsification",
    ]
    fields = _field_map(raw_fields)
    assert set(expected_labels).issubset(fields)
    grid = page.locator("[data-main-panel] .tui-detail-grid").first
    viewport = page.viewport_size
    assert viewport is not None
    for key, expected_label in expected_labels.items():
        field = fields[key]
        assert field["label"] == expected_label
        assert field["value"].strip()
        label = grid.locator("dt").filter(has_text=expected_label)
        assert label.count() == 1
        label.wait_for(state="visible")
        assert label.inner_text().strip() == expected_label
        value = label.locator("xpath=following-sibling::dd[1]")
        value.wait_for(state="visible")
        assert value.inner_text().strip() == field["value"].strip()
        for item in (label, value):
            box = item.bounding_box()
            assert box is not None
            assert box["width"] > 0 and box["height"] > 0
            assert 0 <= box["x"] and box["x"] + box["width"] <= viewport["width"]
            assert 0 <= box["y"] and box["y"] + box["height"] <= viewport["height"]
    return fields


def _action_ui_key(action_key: str) -> str:
    """Match the production task-screen selector published by TUI metadata."""

    digest = hashlib.sha1(action_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"task-{digest}"


@pytest.fixture
def subprocess_policy() -> Iterator[None]:
    """Use the existing Playwright-compatible Windows process policy."""

    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_policy)


def _row_map(rows: object) -> dict[str, dict[str, str]]:
    """Index the real projected rows by their displayed fixture asset name."""

    assert isinstance(rows, list)
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        assert isinstance(row, dict)
        fields = _field_map(row.get("fields"))
        asset = fields.get("asset")
        assert asset is not None
        indexed[asset["value"]] = {key: value["value"] for key, value in fields.items()}
    return indexed


def _save_local_receipt(
    *,
    repository_root: Path,
    owner_call: dict[str, Any],
    browser_requests: list[dict[str, Any]],
    view_model: dict[str, Any],
    account_id: int,
    screenshot_bytes: bytes,
    replay_observation: dict[str, object],
) -> Path:
    """Keep this candidate's source-qualified run files in the ignored workspace."""

    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    run_directory = (
        repository_root / ".tmp" / "m1-temporary-target-browser-preparation-r2" / "runs" / run_key
    )
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "positive-first-viewport.png").write_bytes(screenshot_bytes)
    (run_directory / "actual-view-model.json").write_text(
        json.dumps(view_model, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "evidence_kind": SYNTHETIC_EVIDENCE_KIND,
        "production_m1_acceptance": False,
        "source_note": (
            "Synthetic typed source fixtures; ordinary owner; real Django owner route, "
            "real TUI action/service/projector and real browser renderer. Browser HTTP "
            "uses a single-process Playwright route to Django test Client transport."
        ),
        "account_id": account_id,
        "screenshot_scope": "real_browser_first_viewport_before_detail_expansion",
        "idempotency_replay_observation": replay_observation,
        "owner_status_code": owner_call["status_code"],
        "owner_endpoint": owner_call["endpoint"],
        "owner_payload": owner_call["payload"],
        "browser_requests": browser_requests,
        "view_model": view_model,
    }
    (run_directory / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_directory


def _model_rows_snapshot(
    model: type[Model],
    *,
    filters: dict[str, object],
) -> tuple[tuple[object, ...], ...]:
    """Snapshot all persisted fields for one test-owned model scope."""

    columns = tuple(field.attname for field in model._meta.concrete_fields)
    queryset = model._base_manager.filter(**filters).order_by("pk")
    return tuple(tuple(row) for row in queryset.values_list(*columns))


@pytest.mark.django_db(transaction=True)
def test_m1_local_temporary_target_browser_to_owner_route_and_projector(
    monkeypatch: pytest.MonkeyPatch,
    subprocess_policy: None,
    isolated_m1_revision_table: None,
) -> None:
    """Render and replay one synthetic temporary-target preview through the real TUI action."""

    del isolated_m1_revision_table
    assert_native_postgres_test_database()
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    user, account = owner_case._create_owner_account(
        username=f"m1-local-positive-journey-{uuid4().hex}",
        positions=((owner_case.ASSET_SELL, "Local fixture sell security", True),),
        cash=owner_case.Decimal("100000.00"),
        position_quantity=owner_case.Decimal("10000.000000"),
        position_price=owner_case.Decimal("5.0000"),
        max_position_pct=61.0,
        max_total_position_pct=92.0,
        stop_loss_pct=11.5,
    )
    assert user.is_staff is False
    assert user.is_superuser is False
    strategy = owner_case._create_strategy(
        user=user,
        target_weights={owner_case.ASSET_SELL: 0.0, owner_case.ASSET_BUY: 0.4033},
        max_position_pct=70.0,
        max_total_position_pct=94.0,
        stop_loss_pct=13.5,
    )
    rule = PositionManagementRuleModel.objects.get(strategy_id=strategy.pk)
    rule.metadata = {**rule.metadata, "account_id": account.pk}
    rule.save(update_fields=["metadata"])
    monkeypatch.setattr(owner_case, "PRICE_SOURCE", "fixture-current-market-price")
    owner_case._install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user.pk,
        classification_asset_types={owner_case.ASSET_BUY: "equity"},
    )
    owner_case._publish_m1_policy_for_preview(
        monkeypatch,
        client=APIClient(),
        owner=user,
        account=account,
        strategy=strategy,
    )

    owner_calls: list[dict[str, Any]] = []
    browser_requests: list[dict[str, Any]] = []
    browser_idempotency_keys: list[str] = []
    browser_csrf_tokens: list[str] = []
    projector_calls: list[dict[str, Any]] = []
    bootstrap_observations: list[dict[str, Any]] = []
    from apps.terminal.application import tui_workbench_result_models  # noqa: PLC0415
    from apps.terminal.application.tui_account_inspection_result import (  # noqa: PLC0415
        project_account_inspection_result as production_projector,
    )
    from apps.terminal.interface import api_views  # noqa: PLC0415

    def observed_projector(
        payload: object,
        *,
        requested_account_id: object,
        http_status: int,
    ) -> dict[str, object]:
        projected = production_projector(
            payload,
            requested_account_id=requested_account_id,
            http_status=http_status,
        )
        projector_calls.append(
            {
                "payload": payload,
                "requested_account_id": requested_account_id,
                "http_status": http_status,
                "projected": projected,
            }
        )
        return projected

    monkeypatch.setattr(
        tui_workbench_result_models,
        "project_account_inspection_result",
        observed_projector,
    )
    observed_executor = _ObservedExecutor(TuiInternalActionExecutor(), owner_calls)
    monkeypatch.setattr(
        api_views,
        "get_tui_action_executor",
        lambda: observed_executor,
    )

    before = owner_case._financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = owner_case.RebalanceProposalModel.objects.filter(
        account_id=account.pk
    ).count()
    action_audit_before = _model_rows_snapshot(
        TerminalAuditLogORM,
        filters={"user_id": user.pk, "command_name": ACTION_KEY},
    )
    strategy_before = _model_rows_snapshot(StrategyModel, filters={"pk": strategy.pk})
    rule_before = _model_rows_snapshot(PositionManagementRuleModel, filters={"pk": rule.pk})
    replay_observation: dict[str, object] = {"attempted": False}
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    host = "testserver"
    landing = client.get(f"/tui/?screen={SCREEN_KEY}", HTTP_HOST=host)
    pre_browser_client_response: dict[str, str | int | bool] = {
        "url": _safe_browser_location(f"http://{host}/tui/?screen={SCREEN_KEY}"),
        "method": "GET",
        "status": landing.status_code,
        "test_client_session_cookie_present": settings.SESSION_COOKIE_NAME in client.cookies,
    }
    landing_location = landing.get("Location")
    if landing_location:
        pre_browser_client_response["location"] = _safe_browser_location(landing_location)
    assert landing.status_code == 200
    assert "agomtui-runtime-core.js" in landing.content.decode("utf-8")
    connections.close_all()
    repository_root = Path(settings.BASE_DIR).resolve()

    page_errors: list[str] = []
    browser_request_events: list[dict[str, str | int | bool]] = []
    browser_response_events: list[dict[str, str | int]] = []
    browser_redirects: list[dict[str, str]] = []
    failed_requests: list[dict[str, str]] = []
    route_dispatches: list[dict[str, str | int | bool]] = []

    def observe_browser_request(request: Request) -> None:
        browser_request_events.append(
            {
                "url": _safe_browser_location(request.url),
                "method": request.method,
                "resource_type": request.resource_type,
                "session_cookie_present": settings.SESSION_COOKIE_NAME
                in parse_cookie(request.headers.get("cookie", "")),
            }
        )
        redirected_from = request.redirected_from
        if redirected_from is not None:
            browser_redirects.append(
                {
                    "from": _safe_browser_location(redirected_from.url),
                    "to": _safe_browser_location(request.url),
                }
            )

    def observe_browser_response(response: Response) -> None:
        browser_response_events.append(
            {
                "url": _safe_browser_location(response.url),
                "method": response.request.method,
                "status": response.status,
            }
        )

    def observe_failed_request(request: Request) -> None:
        failed_requests.append(
            {
                "url": _safe_browser_location(request.url),
                "method": request.method,
                "error": request.failure or "unknown browser request failure",
            }
        )

    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(_playwright_cookies(client, host=host))
        page: Page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
        page.on("request", observe_browser_request)
        page.on("response", observe_browser_response)
        page.on("requestfailed", observe_failed_request)

        def dispatch_browser_request(route: Route) -> None:
            request = route.request
            route_dispatches.append(
                {
                    "event": "route_callback_before",
                    "url": _safe_browser_location(request.url),
                    "method": request.method,
                }
            )
            _dispatch_browser_request(
                route,
                client=client,
                host=host,
                browser_requests=browser_requests,
                route_dispatches=route_dispatches,
                bootstrap_observations=bootstrap_observations,
                browser_idempotency_keys=browser_idempotency_keys,
                browser_csrf_tokens=browser_csrf_tokens,
            )

        page.route("**/*", dispatch_browser_request)
        try:
            page.goto(
                f"http://{host}/tui/?screen={SCREEN_KEY}",
                wait_until="networkidle",
            )
            ui_key = _action_ui_key(ACTION_KEY)
            action_form = page.locator(
                f'[data-main-panel] [data-dashboard-panel="{DASHBOARD_PANEL_KEY}"] '
                f'form[data-action-ui-key="{ui_key}"]'
            )
            assert action_form.count() == 1
            action_form.wait_for(state="visible")
            account_select = action_form.locator('select[name="account_id"]')
            option_values = account_select.locator("option").evaluate_all(
                "options => options.map(option => option.value).filter(Boolean)"
            )
            assert str(account.pk) in option_values
            assert account_select.locator(f'option[value="{account.pk}"]').count() == 1
            account_option_text = account_select.locator(
                f'option[value="{account.pk}"]'
            ).inner_text()
            assert account.account_name in account_option_text
            account_select.select_option(str(account.pk))
            price_basis_select = action_form.locator('select[name="reference_price_basis"]')
            assert price_basis_select.locator("option").evaluate_all(
                "options => options.map(option => option.value)"
            ) == ["market", "published_close"]
            assert price_basis_select.input_value() == "market"
            target_textarea = action_form.locator('textarea[name="temporary_target_weights"]')
            target_textarea.fill(TARGET_TEXT)
            assert target_textarea.input_value() == TARGET_TEXT

            form_keys = page.locator(
                f'[data-main-panel] [data-dashboard-panel="{DASHBOARD_PANEL_KEY}"] '
                "form[data-action-ui-key]"
            ).evaluate_all("forms => forms.map(form => form.dataset.actionUiKey)")
            assert form_keys == [ui_key]
            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_URL
            ) as confirmation_response_info:
                action_form.locator(".tui-action-submit").click()
            confirmation_response = confirmation_response_info.value
            assert confirmation_response.status == 200
            assert confirmation_response.json()["confirmation_required"] is True
            assert owner_calls == []
            assert owner_case._financial_snapshot() == before
            assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
                report_count_before
            )
            assert (
                owner_case.RebalanceProposalModel.objects.filter(account_id=account.pk).count()
                == proposal_count_before
            )

            confirmation = page.locator("[data-confirm-action]")
            confirmation.wait_for(state="visible")
            with page.expect_response(
                lambda response: urlsplit(response.url).path == ACTION_URL
            ) as result_response_info:
                confirmation.click()
            result_response = result_response_info.value
            assert result_response.status == 200
            envelope = result_response.json()
            assert envelope["outcome"] in {"success", "partial"}
            assert envelope["response"]["status_code"] == 200
            view_model = envelope["view_model"]
            assert isinstance(view_model, dict)
            assert view_model["kind"] == "detail"
            assert view_model["title"] == "账户调仓预览"
            assert view_model["outcome"] in {"success", "partial"}
            assert isinstance(view_model.get("business_summary"), str)
            assert view_model["business_summary"]
            assert isinstance(view_model.get("status"), str)
            assert view_model["status"]
            result_summary = page.locator("[data-main-panel] [data-task-result-summary]")
            result_summary.wait_for(state="visible")
            assert view_model["business_summary"] in result_summary.inner_text()
            assert action_form.count() == 0
            assert view_model.get("next_steps") == []
            price_basis_field = next(
                field for field in view_model["fields"] if field["key"] == "reference_price_basis"
            )
            assert price_basis_field["value"] == "当前市场参考价（仅本次只读预览）"
            assert page.locator("[data-main-panel] [data-next-step-index]").count() == 0
            assert owner_calls and len(owner_calls) == 1
            owner_call = owner_calls[0]
            assert owner_call["method"] == "POST"
            assert owner_call["endpoint"] == (
                f"/api/account/accounts/{account.pk}/inspections/run/"
            )
            assert owner_call["status_code"] == 200
            assert owner_call["params"] == {}
            assert owner_call["body"]["temporary_target_weights"] == TARGET_TEXT
            assert owner_call["body"]["reference_price_basis"] == "market"
            assert "auto_create_proposal" not in owner_call["body"]
            assert "strategy_id" not in owner_call["body"]
            assert len(browser_idempotency_keys) == 2
            assert all(browser_idempotency_keys)
            expected_key_hash = hashlib.sha256(
                browser_idempotency_keys[-1].encode("utf-8")
            ).hexdigest()
            assert owner_call["idempotency_key_sha256"] == expected_key_hash
            assert len(projector_calls) == 1
            projector_call = projector_calls[0]
            assert projector_call["requested_account_id"] == account.pk
            assert projector_call["http_status"] == 200
            assert projector_call["payload"] == owner_call["payload"]
            projected_sections = projector_call["projected"]["sections"]
            assert view_model["sections"][: len(projected_sections)] == projected_sections
            assert view_model["sections"][-1]["key"] == "temporary_target_context"

            owner_payload = owner_call["payload"]
            assert isinstance(owner_payload, dict)
            report = owner_payload["reports"][0]
            plan = report["plan"]
            assert report["account_id"] == account.pk
            temporary_target_checks = [
                check
                for check in report["checks"]
                if check.get("scope") == "temporary_target_entry"
                and check.get("source") == "user_entered_temporary"
            ]
            assert len(temporary_target_checks) == 1
            temporary_target_check = temporary_target_checks[0]
            assert temporary_target_check["target_weights"] == EXPECTED_TARGET_WEIGHTS
            assert temporary_target_check["residual_cash_weight"] == EXPECTED_CASH_REMAINDER
            assert plan["plan_kind"] == "rebalance_preview"
            assert plan["read_only"] is True
            assert plan["execution_submitted"] is False
            source_rows = {row["asset_code"]: row for row in plan["asset_items"]}
            assert set(source_rows) == {owner_case.ASSET_SELL, owner_case.ASSET_BUY}
            assert source_rows[owner_case.ASSET_SELL]["action"] == "sell"
            assert owner_case.Decimal(source_rows[owner_case.ASSET_SELL]["actionable_quantity"]) > 0
            assert source_rows[owner_case.ASSET_BUY]["action"] == "buy"
            assert source_rows[owner_case.ASSET_BUY]["status"] == "conditional", source_rows[
                owner_case.ASSET_BUY
            ]
            assert owner_case.Decimal(source_rows[owner_case.ASSET_BUY]["suggested_quantity"]) > 0
            assert source_rows[owner_case.ASSET_BUY]["actionable_quantity"] is None

            sections = {section["key"]: section for section in view_model["sections"]}
            target_fields = _field_map(sections["temporary_target_context"]["fields"])
            target_values_by_label = {
                field["label"]: field["value"] for field in target_fields.values()
            }
            assert target_values_by_label == {
                "目标来源": "用户本次填写；未保存为策略配置或自动交易规则",
                "000001.SZ 目标比例": "40.330001%",
                "600000.SH 目标比例": "0%",
                "未分配目标现金权重": "59.669999%",
            }
            asset_rows = _row_map(sections["asset_quantity_plan"]["rows"])
            sell_row = asset_rows["Local fixture sell security"]
            buy_row = asset_rows[owner_case.ASSET_BUY]
            assert sell_row["direction"] == "建议减少"
            assert owner_case.Decimal(sell_row["actionable"]) > 0
            assert buy_row["direction"] == "建议增加"
            assert owner_case.Decimal(buy_row["suggested"]) > 0
            assert buy_row["actionable"] == "待卖出资金完成交收后确认"
            assert "附条件" in buy_row["status"]

            fee_rows = _row_map(sections["asset_cost_identity_review"]["rows"])
            sell_fee = fee_rows["Local fixture sell security"]["fees"]
            buy_fee = fee_rows[owner_case.ASSET_BUY]["fees"]
            for fee_text in (sell_fee, buy_fee):
                assert "佣金" in fee_text
                assert "过户费" in fee_text
                assert "印花税" in fee_text
                assert "滑点估算" in fee_text
                assert "费用合计" in fee_text
            assert "印花税 0" not in sell_fee
            assert "佣金 0" not in sell_fee
            assert owner_case.Decimal(source_rows[owner_case.ASSET_SELL]["fee"]["stamp_duty"]) > 0
            assert owner_case.Decimal(source_rows[owner_case.ASSET_SELL]["fee"]["commission"]) > 0

            cash_fields = _field_map(sections["cash_and_cost_estimates"]["fields"])
            for key in (
                "cash_before",
                "reserved_cash",
                "available_cash_before",
                "projected_cash_after_sells",
                "estimated_sell_gross",
                "estimated_sell_fees",
                "estimated_sell_net",
                "estimated_buy_gross",
                "estimated_buy_fees",
                "estimated_buy_total",
                "projected_cash_after_buys",
            ):
                assert cash_fields[key]["value"] not in {"未提供", "格式未确认"}
            assert plan["funding_status"] == "conditional"

            risk_fields = _field_map(sections["selected_strategy_and_risk_limits"]["fields"])
            for key, expected in EXPECTED_RISK_VALUES.items():
                field = risk_fields[key]
                assert field["value"].endswith("%")
                assert owner_case.Decimal(field["value"].removesuffix("%")) == owner_case.Decimal(
                    expected
                )

            primary_fields = _assert_primary_fields_in_first_viewport(page, view_model)
            top_fields = _field_map(view_model.get("fields"))
            risk_falsification = plan["risk_context"]["risk_falsification"]
            assert risk_falsification["status"] == "not_falsified"
            assert risk_fields["risk_falsification"]["value"] == "当前观察未证伪"
            assert (
                top_fields["risk_falsification"]["value"]
                == risk_fields["risk_falsification"]["value"]
            )
            assert "只读预览，未提交交易" in primary_fields["p0_scope_time"]["value"]
            assert (
                top_fields["inspection_date"]["value"] in primary_fields["p0_scope_time"]["value"]
            )
            assert top_fields["as_of"]["value"] in primary_fields["p0_scope_time"]["value"]
            provenance_fields = _field_map(sections["asset_source_times"]["fields"])
            assert (
                provenance_fields["observed_at"]["value"]
                in primary_fields["p0_scope_time"]["value"]
            )
            first_target_label = next(
                label for label in target_values_by_label if label.endswith("目标比例")
            )
            assert first_target_label in primary_fields["p0_target_cash"]["value"]
            assert (
                target_values_by_label[first_target_label]
                in primary_fields["p0_target_cash"]["value"]
            )
            assert (
                target_values_by_label["未分配目标现金权重"]
                in primary_fields["p0_target_cash"]["value"]
            )
            assert "其余1项目标比例见下方本次临时目标" in primary_fields["p0_target_cash"]["value"]
            first_quantity_row = next(iter(asset_rows.values()))
            for key in ("direction", "current", "sellable", "target", "suggested", "actionable"):
                assert first_quantity_row[key] in primary_fields["p0_first_asset"]["value"]
            assert "另有1项见完整数量建议" in primary_fields["p0_first_asset"]["value"]
            for key in (
                "available_cash_before",
                "estimated_sell_fees",
                "estimated_buy_fees",
                "projected_cash_after_buys",
            ):
                assert cash_fields[key]["value"] in primary_fields["p0_fees_cash"]["value"]
            assert "本次未提供" in primary_fields["p0_fees_cash"]["value"]
            assert "币种本次未提供" in primary_fields["p0_fees_cash"]["value"]
            snapshot_read_at = cash_fields.get("financial_snapshot_read_at", {}).get(
                "value", "未提供"
            )
            assert snapshot_read_at in primary_fields["p0_scope_time"]["value"]
            for key in EXPECTED_RISK_VALUES:
                assert risk_fields[key]["value"] in primary_fields["p0_applicable_limits"]["value"]

            main_panel = page.locator("[data-main-panel]")
            assert page.evaluate("() => window.scrollY") == 0
            assert main_panel.evaluate("element => element.scrollTop") == 0
            business_summary_locator = main_panel.get_by_text(
                view_model["business_summary"], exact=True
            )
            business_summary_locator.wait_for(state="visible")
            business_summary_box = business_summary_locator.bounding_box()
            assert business_summary_box is not None
            viewport_size = page.viewport_size
            assert viewport_size is not None
            assert 0 <= business_summary_box["x"]
            assert (
                business_summary_box["x"] + business_summary_box["width"] <= viewport_size["width"]
            )
            assert 0 <= business_summary_box["y"]
            assert (
                business_summary_box["y"] + business_summary_box["height"]
                <= viewport_size["height"]
            )
            status_locator = main_panel.get_by_text(view_model["status"], exact=True).first
            assert status_locator.is_visible()
            status_box = status_locator.bounding_box()
            assert status_box is not None
            assert 0 <= status_box["x"]
            assert status_box["x"] + status_box["width"] <= viewport_size["width"]
            assert 0 <= status_box["y"]
            assert status_box["y"] + status_box["height"] <= viewport_size["height"]
            first_viewport_screenshot = page.screenshot(
                full_page=False,
                animations="disabled",
            )

            initial_body = next(
                request["json_body"]
                for request in browser_requests
                if request["method"] == "POST" and request["path"] == ACTION_URL
            )
            assert initial_body == {
                "params": {
                    "account_id": account.pk,
                    "temporary_target_weights": TARGET_TEXT,
                    "reference_price_basis": "market",
                },
                "confirmed": False,
            }
            final_body = [
                request["json_body"]
                for request in browser_requests
                if request["method"] == "POST" and request["path"] == ACTION_URL
            ][-1]
            assert isinstance(final_body, dict)
            assert final_body["params"] == {
                "account_id": account.pk,
                "temporary_target_weights": TARGET_TEXT,
                "reference_price_basis": "market",
            }
            assert final_body["confirmed"] is True
            assert final_body["confirmation"]["confirmed"] is True
            assert all(
                request["path"] == ACTION_URL
                for request in browser_requests
                if request["method"] == "POST"
            )

            for title in (
                "单标的数量建议",
                "单标的费用、来源与限制",
                "金额与资金估算",
                "本次采用的策略与风险限制",
                "本次临时目标",
            ):
                matched = False
                detail_sections = page.locator("[data-main-panel] [data-detail-section]")
                for index in range(detail_sections.count()):
                    detail = detail_sections.nth(index)
                    if title in detail.locator("summary").inner_text():
                        if detail.get_attribute("open") is None:
                            detail.locator("summary").click()
                        matched = True
                        break
                assert matched, f"Rendered preview section is missing: {title}"

            main_text = page.locator("[data-main-panel]").inner_text()
            assert "Local fixture sell security" in main_text
            assert owner_case.ASSET_BUY in main_text
            assert "目标来源" in main_text
            for label, value in target_values_by_label.items():
                assert label in main_text
                assert value in main_text
            assert sell_fee in main_text
            assert buy_fee in main_text
            for field in cash_fields.values():
                assert field["label"] in main_text
                assert field["value"] in main_text
            for key in EXPECTED_RISK_VALUES:
                assert risk_fields[key]["label"] in main_text
                assert risk_fields[key]["value"] in main_text
            execution_buttons = page.locator("[data-main-panel] button").all_inner_texts()
            assert not any(
                any(token in label for token in ("下单", "买入", "卖出", "提交委托", "执行交易"))
                for label in execution_buttons
            )
            assert page_errors == []

            report_count_after = DailyInspectionReportModel.objects.filter(
                account_id=account.pk
            ).count()
            proposal_count_after = owner_case.RebalanceProposalModel.objects.filter(
                account_id=account.pk
            ).count()
            assert owner_case._financial_snapshot() == before
            assert report_count_after == report_count_before + 1
            assert proposal_count_after == proposal_count_before
            assert (
                _model_rows_snapshot(StrategyModel, filters={"pk": strategy.pk}) == strategy_before
            )
            assert _model_rows_snapshot(PositionManagementRuleModel, filters={"pk": rule.pk}) == (
                rule_before
            )

            report_rows_after_first = _model_rows_snapshot(
                DailyInspectionReportModel,
                filters={"account_id": account.pk},
            )
            report_business_fields_after_first = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list(
                    "status",
                    "macro_regime",
                    "policy_gear",
                    "total_value",
                    "current_cash",
                    "current_market_value",
                    "checks",
                    "summary",
                )
            )
            report_updated_at_after_first = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list("updated_at", flat=True)
            )
            action_audit_after_first = _model_rows_snapshot(
                TerminalAuditLogORM,
                filters={"user_id": user.pk, "command_name": ACTION_KEY},
            )
            assert len(action_audit_after_first) == len(action_audit_before) + 2
            proposal_count_after_first = proposal_count_after
            assert len(browser_idempotency_keys) == 2
            assert browser_csrf_tokens[-1]
            replay_key = browser_idempotency_keys[-1]
            replay_observation = {
                "attempted": True,
                "same_idempotency_key_as_confirmed_click": True,
                "idempotency_key_sha256": expected_key_hash,
                "report_count_after_first": report_count_after,
                "terminal_audit_rows_after_first": len(action_audit_after_first),
            }
            replay_response = page.evaluate(
                """async ({actionUrl, requestBody, idempotencyKey, csrfToken}) => {
                    const response = await fetch(actionUrl, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": csrfToken,
                            "Idempotency-Key": idempotencyKey
                        },
                        body: JSON.stringify(requestBody)
                    });
                    let payload = {};
                    try { payload = await response.json(); } catch (_) {}
                    return {
                        status: response.status,
                        outcome: typeof payload.outcome === "string" ? payload.outcome : "",
                        confirmation_required: payload.confirmation_required === true,
                        view_model: payload && typeof payload.view_model === "object"
                            ? payload.view_model : null
                    };
                }""",
                {
                    "actionUrl": ACTION_URL,
                    "requestBody": final_body,
                    "idempotencyKey": replay_key,
                    "csrfToken": browser_csrf_tokens[-1],
                },
            )
            assert replay_response["status"] == 200
            assert replay_response["outcome"] in {"success", "partial"}
            assert replay_response["confirmation_required"] is False
            assert len(browser_idempotency_keys) == 3
            assert browser_idempotency_keys[2] == replay_key
            assert isinstance(replay_response["view_model"], dict)
            replay_sections = {
                section["key"]: section for section in replay_response["view_model"]["sections"]
            }
            replay_target_fields = _field_map(replay_sections["temporary_target_context"]["fields"])
            replay_target_values_by_label = {
                field["label"]: field["value"] for field in replay_target_fields.values()
            }
            assert replay_target_values_by_label == target_values_by_label

            replay_owner_call_count = len(owner_calls) - 1
            replay_owner_call: dict[str, Any] | None = None
            replay_owner_target_binding_verified: bool | None = None
            if replay_owner_call_count:
                assert replay_owner_call_count == 1
                replay_owner_call = owner_calls[-1]
                assert replay_owner_call["method"] == "POST"
                assert replay_owner_call["endpoint"] == (
                    f"/api/account/accounts/{account.pk}/inspections/run/"
                )
                assert replay_owner_call["status_code"] == 200
                assert replay_owner_call["idempotency_key_sha256"] == expected_key_hash
                assert replay_owner_call["body"]["temporary_target_weights"] == TARGET_TEXT
                assert replay_owner_call["body"]["reference_price_basis"] == "market"
                assert "strategy_id" not in replay_owner_call["body"]
                replay_owner_payload = replay_owner_call["payload"]
                assert isinstance(replay_owner_payload, dict)
                assert replay_owner_payload["success"] is True
                assert replay_owner_payload["count"] == 1
                replay_report = replay_owner_payload["reports"][0]
                assert replay_report["account_id"] == account.pk
                assert replay_report["report_id"] == report["report_id"]
                replay_target_checks = [
                    check
                    for check in replay_report["checks"]
                    if check.get("scope") == "temporary_target_entry"
                    and check.get("source") == "user_entered_temporary"
                ]
                assert len(replay_target_checks) == 1
                replay_target_check = replay_target_checks[0]
                assert replay_target_check["target_weights"] == EXPECTED_TARGET_WEIGHTS
                assert replay_target_check["residual_cash_weight"] == EXPECTED_CASH_REMAINDER
                replay_owner_target_binding_verified = True

            report_rows_after_replay = _model_rows_snapshot(
                DailyInspectionReportModel,
                filters={"account_id": account.pk},
            )
            report_business_fields_after_replay = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list(
                    "status",
                    "macro_regime",
                    "policy_gear",
                    "total_value",
                    "current_cash",
                    "current_market_value",
                    "checks",
                    "summary",
                )
            )
            report_updated_at_after_replay = tuple(
                DailyInspectionReportModel._base_manager.filter(account_id=account.pk)
                .order_by("pk")
                .values_list("updated_at", flat=True)
            )
            action_audit_after_replay = _model_rows_snapshot(
                TerminalAuditLogORM,
                filters={"user_id": user.pk, "command_name": ACTION_KEY},
            )
            report_count_after_replay = DailyInspectionReportModel.objects.filter(
                account_id=account.pk
            ).count()
            proposal_count_after_replay = owner_case.RebalanceProposalModel.objects.filter(
                account_id=account.pk
            ).count()
            financial_snapshot_after_replay = owner_case._financial_snapshot()
            strategy_after_replay = _model_rows_snapshot(
                StrategyModel,
                filters={"pk": strategy.pk},
            )
            rule_after_replay = _model_rows_snapshot(
                PositionManagementRuleModel,
                filters={"pk": rule.pk},
            )
            replay_observation.update(
                {
                    "report_count_after_replay": report_count_after_replay,
                    "report_row_count_delta": report_count_after_replay - report_count_after,
                    "report_row_snapshot_changed": (
                        report_rows_after_replay != report_rows_after_first
                    ),
                    "report_business_fields_changed": (
                        report_business_fields_after_replay != report_business_fields_after_first
                    ),
                    "report_updated_at_changed": (
                        report_updated_at_after_replay != report_updated_at_after_first
                    ),
                    "terminal_audit_rows_after_replay": len(action_audit_after_replay),
                    "terminal_audit_row_delta": (
                        len(action_audit_after_replay) - len(action_audit_after_first)
                    ),
                    "terminal_audit_snapshot_changed": (
                        action_audit_after_replay != action_audit_after_first
                    ),
                    "proposal_count_after_replay": proposal_count_after_replay,
                    "financial_snapshot_unchanged": financial_snapshot_after_replay == before,
                    "strategy_snapshot_unchanged": strategy_after_replay == strategy_before,
                    "position_rule_snapshot_unchanged": rule_after_replay == rule_before,
                    "owner_call_count_after_replay": len(owner_calls),
                    "replay_owner_call_count": replay_owner_call_count,
                    "same_idempotency_key_sent_to_tui_action": (
                        browser_idempotency_keys[2] == replay_key
                    ),
                    "replay_owner_route_key_forwarded": (
                        None
                        if replay_owner_call is None
                        else replay_owner_call["idempotency_key_sha256"] == expected_key_hash
                    ),
                    "replay_target_binding_verified": replay_target_values_by_label
                    == target_values_by_label,
                    "replay_owner_payload_target_binding_verified": (
                        replay_owner_target_binding_verified
                    ),
                    "replay_outcome": replay_response["outcome"],
                }
            )
            assert report_count_after_replay == report_count_after
            assert len(report_rows_after_replay) == len(report_rows_after_first)
            assert proposal_count_after_replay == proposal_count_after_first
            assert proposal_count_after_replay == proposal_count_before
            assert financial_snapshot_after_replay == before
            assert strategy_after_replay == strategy_before
            assert rule_after_replay == rule_before

            return_to_workspace = page.locator(
                "[data-main-panel] [data-return-dashboard-workspace]"
            )
            return_to_workspace.wait_for(state="visible")
            assert return_to_workspace.inner_text().strip() == "返回账户调仓预览"
            owner_call_count_before_reentry = len(owner_calls)
            action_post_count_before_reentry = sum(
                request["method"] == "POST" and request["path"] == ACTION_URL
                for request in browser_requests
            )
            return_to_workspace.click()
            action_form.wait_for(state="visible")
            assert action_form.count() == 1
            account_select = action_form.locator('select[name="account_id"]')
            account_select.select_option(str(account.pk))
            price_basis_select = action_form.locator('select[name="reference_price_basis"]')
            target_textarea = action_form.locator('textarea[name="temporary_target_weights"]')
            target_textarea.fill(TARGET_TEXT)
            assert account_select.input_value() == str(account.pk)
            assert price_basis_select.input_value() == "market"
            assert target_textarea.input_value() == TARGET_TEXT
            assert len(owner_calls) == owner_call_count_before_reentry
            assert (
                sum(
                    request["method"] == "POST" and request["path"] == ACTION_URL
                    for request in browser_requests
                )
                == action_post_count_before_reentry
            )

            _save_local_receipt(
                repository_root=repository_root,
                owner_call=owner_call,
                browser_requests=browser_requests,
                view_model=view_model,
                account_id=account.pk,
                screenshot_bytes=first_viewport_screenshot,
                replay_observation=replay_observation,
            )
        except Exception as failure:
            diagnostics_path = _save_failure_diagnostics(
                repository_root=repository_root,
                failure_type=type(failure).__name__,
                current_page_url=page.url,
                pre_browser_client_response=pre_browser_client_response,
                browser_requests=browser_request_events,
                browser_responses=browser_response_events,
                browser_redirects=browser_redirects,
                failed_requests=failed_requests,
                route_dispatches=route_dispatches,
                bootstrap_observations=bootstrap_observations,
                page_errors=page_errors,
                page=page,
                safe_observations={
                    "idempotency_replay": replay_observation,
                    "browser_action_idempotency_hashes": [
                        hashlib.sha256(key.encode("utf-8")).hexdigest()
                        for key in browser_idempotency_keys
                    ],
                },
                first_viewport_screenshot=locals().get("first_viewport_screenshot"),
            )
            print(f"Failure diagnostics: {diagnostics_path}")
            raise
        finally:
            context.close()
            browser.close()
            connections.close_all()
