"""Real local-browser journey for source-only instrument-reference capture."""

from __future__ import annotations

import asyncio
import hashlib
import json
from base64 import urlsafe_b64encode
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha1
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from django.conf import settings
from django.db import close_old_connections
from django.test import Client, override_settings
from playwright.sync_api import Route, expect, sync_playwright

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from shared.config.secrets import AppSecrets, DataSourceSecrets, clear_secrets_cache
from shared.config.tushare import TUSHARE_REQUEST_MODE_REST_PATH
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy

_SCREEN_KEY = "api-library.data-center"
_ACTION_REGISTER = "data-center.instrument-reference-mapping-register"
_ACTION_MAPPING_READ = "data-center.instrument-reference-mapping-read"
_ACTION_CAPTURE = "data-center.instrument-reference-capture"
_ACTION_SNAPSHOT_READ = "data-center.instrument-reference-snapshot-read"
_ACTION_OCCURRENCES_READ = "data-center.instrument-reference-snapshot-occurrences-read"
_ACTION_PATH_PREFIX = "/api/tui/actions/"
_FIELDS = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)
_FIELDS_CSV = ",".join(_FIELDS)


def _fixture_body(list_status: str) -> bytes:
    """Return stable captured bytes for one explicit listed or delisted scope."""

    if list_status == "L":
        items: list[list[str]] = [
            ["600000.SH", "Synthetic listed A", "SSE", "fixture-market", "L", "20000102", ""],
            ["600001.SH", "Synthetic listed B", "SSE", "fixture-market", "L", "20010102", ""],
        ]
    elif list_status == "D":
        items = []
    else:
        raise AssertionError("unexpected stock-basic fixture scope")
    return json.dumps(
        {"code": 0, "msg": None, "data": {"fields": list(_FIELDS), "items": items}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


class _RawBody:
    """Expose bounded identity-encoded bytes through requests' raw stream surface."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def stream(self, amount: int, decode_content: bool = False) -> Iterator[bytes]:
        """Yield the exact local fixture bytes without decoding them."""

        if decode_content is not False:
            raise AssertionError("fixture response decoding was unexpectedly enabled")
        for offset in range(0, len(self._body), amount):
            yield self._body[offset : offset + amount]


class _Response:
    """Provide the minimum real capture-response protocol for one synthetic call."""

    status_code = 200

    def __init__(self, body: bytes) -> None:
        self.headers: Mapping[str, str] = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "identity",
        }
        self.raw = _RawBody(body)
        self.closed = False

    def close(self) -> None:
        """Record that the production client releases every actual response."""

        self.closed = True


class _Session:
    """Return fixture bytes only at the configured Tushare session seam."""

    def __init__(self, calls: list[dict[str, object]]) -> None:
        self.calls = calls
        self.headers: dict[str, str] = {}
        self.proxies: dict[str, str] = {}
        self.trust_env = True
        self.responses: list[_Response] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        """Validate the requested stock-basic scope and return its local response."""

        body = kwargs.get("json")
        if not isinstance(body, dict):
            raise AssertionError("stock-basic request was not JSON")
        params = body.get("params")
        if not isinstance(params, dict):
            raise AssertionError("stock-basic request parameters were not an object")
        status = params.get("list_status")
        if (
            body.get("api_name") != "stock_basic"
            or body.get("fields") != _FIELDS_CSV
            or params.get("exchange") != "SSE"
            or status not in {"L", "D"}
            or kwargs.get("allow_redirects") is not False
            or kwargs.get("stream") is not True
        ):
            raise AssertionError("stock-basic request did not match the explicit fixture scope")
        self.calls.append(
            {
                "path": urlsplit(url).path,
                "api_name": body.get("api_name"),
                "fields": body.get("fields"),
                "exchange": params.get("exchange"),
                "list_status": status,
                "redirects_disabled": kwargs.get("allow_redirects") is False,
                "streamed": kwargs.get("stream") is True,
            }
        )
        response = _Response(_fixture_body(status))
        self.responses.append(response)
        return response


@pytest.fixture
def _browser_subprocess_policy() -> Iterator[None]:
    """Select the repository's compatible subprocess event loop only while Chromium runs."""

    original = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original)


def _action_ui_key(action_key: str) -> str:
    """Return the compiler key for one published action form."""

    digest = sha1(action_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"task-{digest}"


def _action_form(page: Any, action_key: str) -> Any:
    """Find one rendered action form and open its existing overflow group if needed."""

    form = page.locator(
        f'[data-actions-panel] form[data-action-ui-key="{_action_ui_key(action_key)}"]'
    )
    expect(form).to_have_count(1)
    if not form.is_visible():
        details = form.locator("xpath=ancestor::details[1]")
        if details.count() == 1 and details.get_attribute("open") is None:
            details.locator(":scope > summary").click()
    expect(form).to_be_visible()
    return form


def _action_response(page: Any, action_key: str) -> Any:
    """Capture the real action-run response without recording request parameters."""

    expected_path = f"{_ACTION_PATH_PREFIX}{action_key}/run/"
    return page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path
    )


def _read_action(page: Any, action_key: str) -> dict[str, Any]:
    """Submit one read form through the TUI and return its actual result envelope."""

    with _action_response(page, action_key) as response_info:
        _action_form(page, action_key).locator('button[type="submit"]').click()
    response = response_info.value
    assert response.status == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("confirmation_required") is False
    owner_response = payload.get("response")
    assert isinstance(owner_response, dict) and owner_response.get("status_code") == 200
    return payload


def _confirmed_action(page: Any, action_key: str) -> dict[str, Any]:
    """Require the real confirmation dialog before one mutating owner call."""

    form = _action_form(page, action_key)
    with _action_response(page, action_key) as preflight_info:
        form.locator('button[type="submit"]').click()
    preflight_response = preflight_info.value
    assert preflight_response.status == 200
    preflight = preflight_response.json()
    assert isinstance(preflight, dict) and preflight.get("confirmation_required") is True
    modal = page.locator("[data-tui-modal]")
    expect(modal).to_be_visible()
    with _action_response(page, action_key) as confirmed_info:
        modal.locator("[data-confirm-action]").click()
    response = confirmed_info.value
    assert response.status == 200
    result = response.json()
    assert isinstance(result, dict)
    assert result.get("confirmation_required") is False
    owner_response = result.get("response")
    assert isinstance(owner_response, dict) and owner_response.get("status_code") == 200
    expect(modal).to_be_hidden()
    return result


def _detail_value(view_model: dict[str, Any], key: str) -> str:
    """Read one displayed scalar field from the real TUI detail projection."""

    fields = view_model.get("fields")
    assert isinstance(fields, list)
    matches = [
        field.get("value")
        for field in fields
        if isinstance(field, dict) and field.get("key") == key
    ]
    assert len(matches) == 1 and isinstance(matches[0], str)
    return matches[0]


def _view_model(result: dict[str, Any]) -> dict[str, Any]:
    """Return the rendered TUI view model from an action-run response."""

    model = result.get("view_model")
    assert isinstance(model, dict)
    return model


def _session_cookie(user: Any) -> str:
    """Create a database-backed session cookie for the local browser context."""

    client = Client()
    client.force_login(user)
    return client.cookies[settings.SESSION_COOKIE_NAME].value


def _install_transport_and_global_mode(
    monkeypatch: pytest.MonkeyPatch,
    request_calls: list[dict[str, object]],
) -> list[_Session]:
    """Pin the global fallback apart from the saved provider's explicit mode."""

    fallback = AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token="",
            fred_api_key="",
            tushare_http_url=None,
            tushare_request_mode=TUSHARE_REQUEST_MODE_REST_PATH,
        )
    )
    monkeypatch.setattr(tushare_client, "get_secrets", lambda: fallback)
    resolved = tushare_client.resolve_tushare_runtime_settings(
        token="synthetic-browser-fixture",
        http_url="https://fixture.invalid/pro",
    )
    if resolved.request_mode != TUSHARE_REQUEST_MODE_REST_PATH:
        raise AssertionError("global fallback mode was not isolated from provider mode")
    sessions: list[_Session] = []

    def create_local_session() -> _Session:
        session = _Session(request_calls)
        sessions.append(session)
        return session

    monkeypatch.setattr(tushare_client, "_create_requests_session", create_local_session)
    return sessions


def _write_browser_diagnostic(
    tmp_path: Any,
    *,
    status: str,
    phase: str,
    console_issues: list[str],
    page_errors: list[str],
    browser_requests: list[tuple[str, str, str]],
    blocked_browser_hosts: list[str],
    screenshot_name: str | None,
    error_type: str | None,
    expected_background_errors: list[str],
) -> None:
    """Persist a small diagnostic without request URLs, bodies, or credentials."""

    diagnostic = {
        "status": status,
        "expected_background_errors": list(expected_background_errors),
        "phase": phase,
        "console_warning_or_error_types": list(console_issues),
        "page_error_count": len(page_errors),
        "browser_request_count": len(browser_requests),
        "blocked_browser_request_count": len(blocked_browser_hosts),
        "screenshot": screenshot_name,
        "error_type": error_type,
    }
    (tmp_path / f"journey-{status}-diagnostic.json").write_text(
        json.dumps(diagnostic, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _assert_real_confirmation_audits(user_id: int, synthetic_token: str) -> None:
    """Read committed live-server audits in a sync thread without disabling ORM protection."""

    close_old_connections()
    try:
        for action_key in (_ACTION_REGISTER, _ACTION_CAPTURE):
            confirmed_audits = list(
                TerminalAuditLogORM._default_manager.filter(
                    user_id=user_id,
                    command_name=action_key[:50],
                    mode="tui-workbench",
                    confirmation_status="confirmed",
                )
            )
            assert len(confirmed_audits) == 1
            audit_record = confirmed_audits[0]
            assert audit_record.confirmation_required is True
            assert audit_record.result_status == "success"
            assert audit_record.session_id
            canonical_audit = json.loads(audit_record.params_summary)
            assert canonical_audit["action_key"] == action_key
            assert canonical_audit["confirmation"]["confirmed"] is True
            assert canonical_audit["outcome"] == "succeeded"
            assert canonical_audit["result"]["status_code"] == 200
            assert synthetic_token not in audit_record.params_summary
    finally:
        close_old_connections()


@pytest.mark.django_db(transaction=True)
def test_source_only_instrument_reference_capture_from_real_tui_browser(
    live_server: Any,
    django_user_model: Any,
    monkeypatch: pytest.MonkeyPatch,
    _browser_subprocess_policy: None,
    tmp_path: Any,
) -> None:
    """Register, capture, and read exact source-only receipts through the real TUI."""

    suffix = uuid4().hex
    synthetic_token = f"synthetic-browser-fixture-{suffix}"
    synthetic_key = urlsafe_b64encode(bytes(range(32))).decode("ascii")
    user = django_user_model.objects.create_user(
        username=f"instrument-reference-browser-{suffix}",
        password="synthetic-browser-password",
        is_active=True,
        is_staff=True,
    )
    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=None):
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", synthetic_key)
        clear_secrets_cache()
        try:
            request_calls: list[dict[str, object]] = []
            sessions = _install_transport_and_global_mode(monkeypatch, request_calls)
            provider = ProviderConfigRepository().save(
                ProviderConfig(
                    id=None,
                    name=f"instrument-reference-browser-{suffix}",
                    source_type="tushare",
                    is_active=True,
                    priority=1,
                    api_key=synthetic_token,
                    api_secret="",
                    http_url="https://fixture.invalid/pro",
                    api_endpoint="",
                    extra_config={"tushare_request_mode": "unified_relay"},
                    description="Synthetic browser-only fixture; no provider request is sent.",
                )
            )
            if type(provider.id) is not int:
                raise AssertionError("synthetic provider fixture was not persisted")
            session_cookie = _session_cookie(user)
            browser_requests: list[tuple[str, str, str]] = []
            action_confirmations: list[tuple[str, bool | None]] = []
            console_issues: list[str] = []
            expected_background_errors: list[str] = []
            http_errors: list[tuple[str, int]] = []
            page_errors: list[str] = []
            blocked_browser_hosts: list[str] = []
            with sync_playwright() as playwright:
                browser = None
                context = None
                page = None
                phase = "browser_setup"
                try:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context(viewport={"width": 1440, "height": 1000})
                    context.add_cookies(
                        [
                            {
                                "name": settings.SESSION_COOKIE_NAME,
                                "value": session_cookie,
                                "url": live_server.url,
                            }
                        ]
                    )

                    def allow_local_page_requests(route: Route) -> None:
                        """Abort browser traffic unless it targets this live Django server."""

                        parsed = urlsplit(route.request.url)
                        if parsed.netloc != urlsplit(live_server.url).netloc:
                            blocked_browser_hosts.append(parsed.hostname or "unknown-host")
                            route.abort("blockedbyclient")
                            return
                        route.continue_()

                    context.route("**/*", allow_local_page_requests)
                    page = context.new_page()
                    page.on(
                        "request",
                        lambda request: browser_requests.append(
                            (
                                request.method,
                                urlsplit(request.url).netloc,
                                urlsplit(request.url).path,
                            )
                        ),
                    )

                    def capture_action_confirmation(request: Any) -> None:
                        """Keep only action path and the exact confirmation bit."""

                        parsed = urlsplit(request.url)
                        if request.method != "POST" or not parsed.path.startswith(
                            _ACTION_PATH_PREFIX
                        ):
                            return
                        body = request.post_data_json
                        value = body.get("confirmed") if isinstance(body, dict) else None
                        action_confirmations.append(
                            (parsed.path, value if type(value) is bool else None)
                        )

                    page.on("request", capture_action_confirmation)

                    def record_console(message: Any) -> None:
                        """Retain the known absent-calendar background error separately."""

                        if message.type not in {"warning", "error"}:
                            return
                        path = urlsplit(str(message.location.get("url", ""))).path
                        if (
                            message.type == "error"
                            and path == "/api/tui/operator/governance-queue/"
                            and message.text.startswith("Failed to load resource:")
                            and "503" in message.text
                        ):
                            expected_background_errors.append("governance_queue_unavailable_503")
                        else:
                            console_issues.append(message.type)

                    page.on("console", record_console)
                    page.on(
                        "response",
                        lambda response: (
                            http_errors.append((urlsplit(response.url).path, response.status))
                            if response.status >= 400
                            else None
                        ),
                    )
                    page.on("pageerror", lambda _error: page_errors.append("pageerror"))
                    phase = "open_data_center_screen"
                    page.goto(
                        f"{live_server.url}/tui/?screen={_SCREEN_KEY}",
                        wait_until="networkidle",
                    )
                    expect(page.locator("[data-main-panel]")).to_be_visible()
                    page.keyboard.press("F9")
                    expect(page.locator("[data-actions-panel]")).to_be_visible()

                    phase = "register_mapping"
                    mapping_form = _action_form(page, _ACTION_REGISTER)
                    mapping_form.locator('[name="mapping_id"]').fill(
                        f"fixture.instrument-reference.{suffix}"
                    )
                    mapping_form.locator('[name="mapping_version"]').fill("fixture-v1")
                    mapping_form.locator('[name="source_crosswalk_id"]').fill(
                        f"fixture.instrument-reference-crosswalk.{suffix}"
                    )
                    mapping_form.locator('[name="source_crosswalk_version"]').fill("fixture-v1")
                    mapping_form.locator('[name="exchange_suffix_pairs"]').fill(
                        json.dumps([["SSE", "SH"]], separators=(",", ":"))
                    )
                    mapping_form.locator('[name="exchange_rule_market_pairs"]').fill(
                        json.dumps([["SSE", "SSE"]], separators=(",", ":"))
                    )
                    mapping_form.locator('[name="exchange_source_market_board_pairs"]').fill(
                        json.dumps(
                            [["SSE", "fixture-market", "fixture-board"]],
                            separators=(",", ":"),
                        )
                    )
                    registered = _confirmed_action(page, _ACTION_REGISTER)
                    registered_model = _view_model(registered)
                    mapping_id = str(
                        UUID(_detail_value(registered_model, "mapping.mapping_record_id"))
                    )

                    phase = "read_mapping"
                    mapping_read_form = _action_form(page, _ACTION_MAPPING_READ)
                    mapping_read_form.locator('[name="mapping_record_id"]').fill(mapping_id)
                    mapping_read = _read_action(page, _ACTION_MAPPING_READ)
                    assert (
                        _detail_value(_view_model(mapping_read), "mapping.mapping_record_id")
                        == mapping_id
                    )
                    mapping_receipt_response = page.request.get(
                        f"{live_server.url}/api/data-center/tui/instrument-reference/mappings/{mapping_id}/"
                    )
                    assert mapping_receipt_response.status == 200
                    mapping_receipt = mapping_receipt_response.json()
                    assert mapping_receipt["mapping"]["mapping_record_id"] == mapping_id
                    assert (
                        mapping_receipt["mapping"]["owner_or_provider_approval_asserted"] is False
                    )
                    assert mapping_receipt["mapping"]["operator_supplied_only"] is True

                    phase = "capture_source_only_data"
                    capture_id = str(uuid4())
                    capture_form = _action_form(page, _ACTION_CAPTURE)
                    capture_form.locator('[name="capture_id"]').fill(capture_id)
                    capture_form.locator('[name="provider_configuration_id"]').fill(
                        str(provider.id)
                    )
                    capture_form.locator('[name="mapping_record_id"]').fill(mapping_id)
                    capture_form.locator('[name="exchange_scope"]').fill('["SSE"]')
                    capture_form.locator('[name="list_status_scope"]').fill('["L","D"]')
                    capture_form.locator('[name="mode"]').select_option("normal")
                    captured = _confirmed_action(page, _ACTION_CAPTURE)
                    assert captured.get("outcome") == "success"
                    capture_model = _view_model(captured)
                    snapshot_id = str(UUID(_detail_value(capture_model, "snapshot.snapshot_id")))
                    assert _detail_value(capture_model, "snapshot.record_count") == "2"
                    assert _detail_value(capture_model, "snapshot.occurrence_count") == "2"
                    assert _detail_value(capture_model, "snapshot.empty_occurrence_count") == "1"
                    assert _detail_value(capture_model, "snapshot.run_id") == capture_id

                    phase = "read_snapshot_rows"
                    snapshot_form = _action_form(page, _ACTION_SNAPSHOT_READ)
                    snapshot_form.locator('[name="snapshot_id"]').fill(snapshot_id)
                    snapshot_form.locator('[name="limit"]').fill("200")
                    snapshot_form.locator('[name="offset"]').fill("0")
                    snapshot_read = _read_action(page, _ACTION_SNAPSHOT_READ)
                    snapshot_model = _view_model(snapshot_read)
                    assert snapshot_model.get("kind") == "datagrid"
                    assert snapshot_model.get("pager", {}).get("total_rows") == 2
                    assert len(snapshot_model.get("rows", [])) == 2

                    phase = "read_snapshot_occurrences"
                    occurrence_form = _action_form(page, _ACTION_OCCURRENCES_READ)
                    occurrence_form.locator('[name="snapshot_id"]').fill(snapshot_id)
                    occurrence_form.locator('[name="limit"]').fill("200")
                    occurrence_form.locator('[name="offset"]').fill("0")
                    occurrence_read = _read_action(page, _ACTION_OCCURRENCES_READ)
                    occurrence_model = _view_model(occurrence_read)
                    assert occurrence_model.get("kind") == "datagrid"
                    assert occurrence_model.get("pager", {}).get("total_rows") == 2
                    occurrence_rows = occurrence_model.get("rows")
                    assert isinstance(occurrence_rows, list) and len(occurrence_rows) == 2
                    assert sorted(row.get("row_count") for row in occurrence_rows) == ["0", "2"]
                    grid_rows = page.locator("[data-main-panel] .tui-datagrid tbody tr")
                    expect(grid_rows).to_have_count(2)
                    row_count_column = next(
                        index
                        for index, column in enumerate(occurrence_model.get("columns", []))
                        if isinstance(column, dict) and column.get("key") == "row_count"
                    )
                    rendered_counts = [
                        row.locator("td").nth(row_count_column).inner_text()
                        for row in grid_rows.all()
                    ]
                    assert "0" in rendered_counts

                    phase = "verify_snapshot_receipt"
                    exact_read = page.request.get(
                        f"{live_server.url}/api/data-center/tui/instrument-reference/snapshots/{snapshot_id}/?limit=200&offset=0"
                    )
                    assert exact_read.status == 200
                    payload = exact_read.json()
                    assert payload["snapshot"]["snapshot_id"] == snapshot_id
                    assert payload["snapshot"]["mapping_record_id"] == mapping_id
                    assert payload["snapshot"]["mapping_content_hash"] == (
                        mapping_receipt["mapping"]["content_hash"]
                    )
                    assert payload["snapshot"]["run_id"] == capture_id
                    assert payload["snapshot"]["record_count"] == 2
                    assert payload["snapshot"]["occurrence_count"] == 2
                    assert payload["snapshot"]["empty_occurrence_count"] == 1
                    assert payload["snapshot"]["fetch_round_count"] == 1
                    assert payload["snapshot"]["source_observed_at"] is None
                    assert payload["snapshot"]["source_available_at"] is None
                    assert payload["snapshot"]["must_not_use_for_decision"] is True
                    assert payload["snapshot"]["must_not_execute"] is True
                    assert payload["snapshot"]["blocked_reason"] == (
                        "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"
                    )
                    assert payload["total"] == 2 and len(payload["rows"]) == 2
                    assert payload["occurrence_total"] == 2
                    occurrences = payload["occurrences"]
                    assert isinstance(occurrences, list) and len(occurrences) == 2
                    empty = [row for row in occurrences if row.get("list_status") == "D"]
                    assert len(empty) == 1
                    expected_row_count = {"L": 2, "D": 0}
                    for occurrence in occurrences:
                        status = occurrence.get("list_status")
                        assert status in expected_row_count
                        assert occurrence.get("fetch_round_id") == capture_id
                        assert occurrence.get("exchange") == "SSE"
                        assert occurrence.get("row_count") == expected_row_count[status]
                        assert occurrence.get("blocked_reason") == (
                            "INSTRUMENT_REFERENCE_SOURCE_ONLY_NOT_DECISION_READY"
                        )
                        reference = occurrence.get("raw_audit_reference")
                        assert isinstance(reference, dict)
                        assert set(reference) == {
                            "raw_audit_id",
                            "version",
                            "content_hash",
                            "run_id",
                            "ingested_run_id",
                        }
                        flattened_reference_fields = {
                            "raw_audit_id": "raw_audit_id",
                            "version": "raw_audit_version",
                            "content_hash": "raw_audit_content_hash",
                            "run_id": "raw_audit_run_id",
                            "ingested_run_id": "raw_audit_ingested_run_id",
                        }
                        for reference_key, occurrence_key in flattened_reference_fields.items():
                            assert occurrence.get(occurrence_key) == reference[reference_key]
                        expected_hash = hashlib.sha256(_fixture_body(status)).hexdigest()
                        assert occurrence.get("response_body_sha256") == expected_hash
                        assert occurrence.get("raw_payload_hash")
                        assert occurrence.get("response_completed_at")
                        assert occurrence.get("source_observed_at") is None
                        assert occurrence.get("source_available_at") is None
                        assert occurrence.get("upstream_time_unknown") is True
                        assert occurrence.get("must_not_use_for_decision") is True
                        assert occurrence.get("must_not_execute") is True
                    assert all(
                        row.get("must_not_use_for_decision") is True for row in payload["rows"]
                    )
                    assert all(row.get("must_not_execute") is True for row in payload["rows"])

                    with ThreadPoolExecutor(max_workers=1) as audit_reader:
                        audit_reader.submit(
                            _assert_real_confirmation_audits, user.pk, synthetic_token
                        ).result(timeout=15)

                    expected_confirmation_prefix = f"{_ACTION_PATH_PREFIX}"
                    for action_key in (_ACTION_REGISTER, _ACTION_CAPTURE):
                        action_path = f"{expected_confirmation_prefix}{action_key}/run/"
                        flags = [
                            value for path, value in action_confirmations if path == action_path
                        ]
                        assert len(flags) == 2 and flags.count(True) == 1
                    assert [call["list_status"] for call in request_calls] == ["L", "D"]
                    assert all(call["api_name"] == "stock_basic" for call in request_calls)
                    assert all(call["fields"] == _FIELDS_CSV for call in request_calls)
                    assert all(
                        call["redirects_disabled"] and call["streamed"] for call in request_calls
                    )
                    assert sessions and all(
                        response.closed for session in sessions for response in session.responses
                    )
                    expected_origin = urlsplit(live_server.url).netloc
                    assert all(
                        origin == expected_origin for _method, origin, _path in browser_requests
                    )
                    assert blocked_browser_hosts == []
                    assert all(
                        path == "/api/tui/operator/governance-queue/" and status == 503
                        for path, status in http_errors
                    ), http_errors
                    if expected_background_errors or http_errors:
                        blocked_queue = page.request.get(
                            f"{live_server.url}/api/tui/operator/governance-queue/"
                        )
                        assert blocked_queue.status == 503
                        assert blocked_queue.json()["success"] is False
                        assert blocked_queue.json()["must_not_use_for_decision"] is True
                        assert (
                            blocked_queue.json()["blocked_reason"] == "governance_queue_unavailable"
                        )
                    assert console_issues == []
                    assert page_errors == []
                    phase = "save_success_evidence"
                    screenshot = tmp_path / "journey-success.png"
                    page.screenshot(path=str(screenshot), full_page=True)
                    _write_browser_diagnostic(
                        tmp_path,
                        status="success",
                        phase=phase,
                        console_issues=console_issues,
                        page_errors=page_errors,
                        browser_requests=browser_requests,
                        blocked_browser_hosts=blocked_browser_hosts,
                        screenshot_name=screenshot.name,
                        error_type=None,
                        expected_background_errors=expected_background_errors,
                    )
                except BaseException as error:
                    screenshot_name = None
                    if page is not None:
                        try:
                            screenshot = tmp_path / "journey-failure.png"
                            page.screenshot(path=str(screenshot), full_page=True)
                            screenshot_name = screenshot.name
                        except Exception:
                            screenshot_name = None
                    _write_browser_diagnostic(
                        tmp_path,
                        status="failure",
                        phase=phase,
                        console_issues=console_issues,
                        page_errors=page_errors,
                        browser_requests=browser_requests,
                        blocked_browser_hosts=blocked_browser_hosts,
                        screenshot_name=screenshot_name,
                        error_type=type(error).__name__,
                        expected_background_errors=expected_background_errors,
                    )
                    raise
                finally:
                    try:
                        if context is not None:
                            context.close()
                    finally:
                        if browser is not None:
                            browser.close()
        finally:
            clear_secrets_cache()
