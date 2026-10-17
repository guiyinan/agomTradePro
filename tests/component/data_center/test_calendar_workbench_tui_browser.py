"""Native browser journey for the Calendar Workbench TUI."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ParamSpec, TypeVar, cast
from urllib.parse import urlsplit
from uuid import uuid4
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.handlers.wsgi import WSGIHandler
from django.db import connection, connections
from django.test import override_settings
from django.utils import timezone
from pytest_django.plugin import DjangoDbBlocker

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.terminal.infrastructure.models import TerminalAuditLogORM
from shared.config.secrets import clear_secrets_cache
from tests.component.data_center.test_calendar_workbench_http import (
    _ENCRYPTION_KEY,
    _HTTP_SCHEMA_MODELS,
    _calendar_body,
    _formal_counts,
    _install_source,
    _source_counts,
)
from tests.component.data_center.test_calendar_workbench_tui_http import (
    _assert_continuation_is_not_audited,
    _install_actual_calendar_runtime,
)
from tests.component.data_center.test_formal_calendar_publication_postgres import (
    _actual_publisher,
)
from tests.support.isolated_schema import isolated_schema
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)
from tests.support.native_postgres_database import (  # noqa: F401
    native_postgres_test_database as _native_postgres_test_database_fixture,
)

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Calendar TUI browser journey requires its explicit Native PostgreSQL database",
)

_SCREEN_KEY = "data-center.calendar-workbench"
_ACTION_PREFIX = "data-center.calendar-workbench-"
_TEST_USERNAME_PREFIX = f"calendar-browser-{uuid4().hex}-"
_PASSWORD = "CalendarBrowserFixture!42"
_HTTP_COMPONENT_LABELS = frozenset({"audit", "config_center", "data_center"})
_COMPONENT_SCHEMA_MODELS = tuple(
    model for model in _HTTP_SCHEMA_MODELS if model._meta.app_label in _HTTP_COMPONENT_LABELS
) + (TerminalAuditLogORM,)
_P = ParamSpec("_P")
_R = TypeVar("_R")


class _QuietRequestHandler(WSGIRequestHandler):
    """Keep local HTTP request details out of test output."""

    def log_message(self, format: str, *args: object) -> None:
        """Suppress the WSGI server's request-line logging."""

        del format, args


@pytest.fixture(scope="session")
def django_db_setup(native_postgres_test_database: str) -> str:
    """Use only the explicit Native database configured by TEST.NAME."""

    return native_postgres_test_database


@pytest.fixture(autouse=True)
def _isolated_calendar_browser_rows(
    django_db_setup: str,
    django_db_blocker: DjangoDbBlocker,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate Calendar tables without flushing auth, profile, or singleton rows."""

    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")

    def verify_test_database() -> None:
        """Guard every cleanup against a database alias/name change."""

        assert_native_postgres_test_database(expected_name=django_db_setup)

    with django_db_blocker.unblock():
        verify_test_database()
        existing_session_keys = set(Session.objects.values_list("session_key", flat=True))
        try:
            with isolated_schema(
                _COMPONENT_SCHEMA_MODELS,
                before_cleanup=verify_test_database,
            ):
                yield
        finally:
            verify_test_database()
            created_session_keys = tuple(
                Session.objects.exclude(session_key__in=existing_session_keys).values_list(
                    "session_key", flat=True
                )
            )
            if created_session_keys:
                Session.objects.filter(session_key__in=created_session_keys).delete()
            get_user_model().objects.filter(username__startswith=_TEST_USERNAME_PREFIX).delete()
            verify_test_database()


@pytest.fixture(autouse=True)
def _synthetic_capture_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep provider secrets synthetic and scoped to this test process."""

    with override_settings(AGOMTRADEPRO_ENCRYPTION_KEY=None):
        monkeypatch.setenv("AGOMTRADEPRO_ENCRYPTION_KEY", _ENCRYPTION_KEY)
        clear_secrets_cache()
        try:
            yield
        finally:
            clear_secrets_cache()


@pytest.fixture(autouse=True)
def _local_http_cookie_settings() -> Iterator[None]:
    """Allow the actual browser Session/CSRF exchange over the local HTTP socket."""

    with override_settings(
        ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"],
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        SESSION_COOKIE_SECURE=False,
    ):
        yield


@contextmanager
def _serve_local_django() -> Iterator[str]:
    """Serve Django and static files on an ephemeral loopback-only HTTP port."""

    application = StaticFilesHandler(WSGIHandler())
    server = cast(
        WSGIServer,
        make_server(
            "127.0.0.1",
            0,
            application,
            handler_class=_QuietRequestHandler,
        ),
    )
    worker = threading.Thread(target=server.serve_forever, name="calendar-tui-http", daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join(timeout=10)
        server.server_close()
        assert not worker.is_alive()


@contextmanager
def _playwright_subprocess_event_loop_policy() -> Iterator[None]:
    """Temporarily select Proactor only for Playwright subprocess startup on Windows."""

    if sys.platform != "win32":
        yield
        return

    original_policy = asyncio.get_event_loop_policy()
    proactor_policy_type = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    changed = proactor_policy_type is not None and not isinstance(
        original_policy, proactor_policy_type
    )
    if changed:
        asyncio.set_event_loop_policy(proactor_policy_type())
    try:
        yield
    finally:
        if changed:
            asyncio.set_event_loop_policy(original_policy)


def _run_database_call(
    function: Callable[_P, _R],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _R:
    """Run synchronous Django ORM work outside Playwright's active asyncio loop."""

    def invoke() -> _R:
        try:
            return function(*args, **kwargs)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="calendar-browser-db") as executor:
        return executor.submit(invoke).result()


def _create_browser_publisher() -> Any:
    """Create a real staff user and persisted calendar publication grant."""

    user, _proof = _actual_publisher(f"{_TEST_USERNAME_PREFIX}publisher")
    user.set_password(_PASSWORD)
    user.is_staff = True
    user.save(update_fields=["password", "is_staff"])
    AccountProfileModel.objects.create(
        user=user,
        display_name="Calendar browser fixture",
        mcp_enabled=True,
    )
    return user


def _create_browser_regular_user(*, approved_by: Any) -> Any:
    """Create an ordinary user with the account profile required by TUI policy."""

    user_model = get_user_model()
    user = user_model.objects.create_user(
        username=f"{_TEST_USERNAME_PREFIX}regular",
        password=_PASSWORD,
        is_active=True,
        is_staff=False,
    )
    AccountProfileModel.objects.create(
        user=user,
        display_name="Calendar regular fixture",
        mcp_enabled=True,
        user_agreement_accepted=True,
        risk_warning_acknowledged=True,
        agreement_accepted_at=timezone.now(),
        approval_status="approved",
        approved_at=timezone.now(),
        approved_by=approved_by,
    )
    return user


def _login_through_form(page: Any, *, base_url: str, username: str) -> None:
    """Create a real browser-authenticated Django session and CSRF cookie."""

    page.goto(f"{base_url}/account/login/", wait_until="networkidle")
    page.locator("#loginForm #username").fill(username)
    page.locator("#loginForm #password").fill(_PASSWORD)
    page.get_by_role("button", name="登录").click()
    page.locator("#tui-location-input").wait_for(state="visible")
    page.wait_for_load_state("networkidle")
    cookie_names = {item["name"] for item in page.context.cookies()}
    assert settings.SESSION_COOKIE_NAME in cookie_names
    assert settings.CSRF_COOKIE_NAME in cookie_names


def _open_calendar_screen(page: Any) -> None:
    """Use the ordinary TUI location control to open the published workbench."""

    location = page.locator("#tui-location-input")
    location.fill(_SCREEN_KEY)
    location.press("Enter")
    scope_form = page.locator("[data-actions-panel]").locator(
        f'[data-action-ui-key="{_action_ui_key("scope")}"]'
    )
    scope_form.wait_for(state="attached")
    page.keyboard.press("F9")
    scope_form.wait_for(state="visible")


def _action_ui_key(suffix: str) -> str:
    """Match the public action form key emitted by the TUI metadata compiler."""

    action_key = _ACTION_PREFIX + suffix
    digest = hashlib.sha1(action_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"task-{digest}"


def _action_form(page: Any, suffix: str) -> Any:
    """Locate one action form by the compiler's stable action-derived UI key."""

    return page.locator("[data-actions-panel]").locator(
        f'[data-action-ui-key="{_action_ui_key(suffix)}"]'
    )


def _main_panel(page: Any) -> Any:
    """Scope user-visible result assertions to the active main result panel."""

    return page.locator("[data-main-panel]")


def _confirmed_action_count(
    action_post_confirmations: list[tuple[str, bool | None]],
    action_suffix: str,
) -> int:
    """Count confirmed owner runs, excluding the TUI's non-operative preflight."""

    target_path = f"/api/tui/actions/{_ACTION_PREFIX}{action_suffix}/run/"
    return sum(
        path == target_path and confirmed is True for path, confirmed in action_post_confirmations
    )


def _run_confirmed_action(page: Any, suffix: str) -> Any:
    """Pass the UI's own confirmation modal before returning the actual response."""

    action_key = _ACTION_PREFIX + suffix
    form = _action_form(page, suffix)
    form.locator('button[type="submit"]').click()
    modal = page.locator("[data-tui-modal]")
    modal.wait_for(state="visible")
    expected_path = f"/api/tui/actions/{action_key}/run/"
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path
    ) as response_info:
        modal.locator("[data-confirm-action]").click()
    response = response_info.value
    assert response.status == 200
    return response


def _run_read_action(page: Any, suffix: str) -> Any:
    """Submit one read form and return its real TUI action-run response."""

    action_key = _ACTION_PREFIX + suffix
    expected_path = f"/api/tui/actions/{action_key}/run/"
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path
    ) as response_info:
        _action_form(page, suffix).locator('button[type="submit"]').click()
    response = response_info.value
    assert response.status == 200
    return response


def _extract_confirmation_token(response: Any) -> str:
    """Capture the machine-only handoff from the outer TUI response in test memory."""

    payload = response.json()
    assert isinstance(payload, dict)
    assert payload.get("outcome") == "success"
    continuation = payload.get("continuation")
    assert isinstance(continuation, dict)
    assert set(continuation) == {"action_key", "input", "expires_at"}
    assert continuation.get("action_key") == _ACTION_PREFIX + "confirm"
    token_input = continuation.get("input")
    assert isinstance(token_input, dict)
    assert set(token_input) == {"confirmation_token"}
    token = token_input.get("confirmation_token")
    assert type(token) is str and token.startswith("encrypted:v1:")
    return token


def _assert_token_not_exposed(page: Any, token: str, *, console: list[str]) -> None:
    """Keep the opaque token out of browser-visible state and diagnostics."""

    browser_state = page.evaluate("""() => JSON.stringify({
            html: document.documentElement.outerHTML,
            text: document.body.innerText,
            url: window.location.href,
            inputs: Array.from(document.querySelectorAll('input')).map(input => input.value),
            local: Array.from({length: localStorage.length}, (_, i) => {
                const key = localStorage.key(i); return [key, key === null ? null : localStorage.getItem(key)];
            }),
            session: Array.from({length: sessionStorage.length}, (_, i) => {
                const key = sessionStorage.key(i); return [key, key === null ? null : sessionStorage.getItem(key)];
            })
        })""")
    assert token not in browser_state
    assert token not in page.url
    assert all(token not in message for message in console)


def _assert_served_bundle_matches_source(
    *,
    page: Any,
    base_url: str,
    responses: list[Any],
) -> None:
    """Verify the browser loaded the exact accepted bundle in its own checkout."""
    matches = [
        response
        for response in responses
        if urlsplit(response.url).path == "/static/js/tui-workbench.js"
    ]
    assert len(matches) == 1
    response = matches[0]
    assert response.status == 200
    served_bundle = response.body()
    source_path = Path(settings.BASE_DIR) / "static" / "js" / "tui-workbench.js"
    source_bundle = source_path.read_bytes()
    assert hashlib.sha256(served_bundle).digest() == hashlib.sha256(source_bundle).digest()
    assert b"result_continuation" in served_bundle
    assert base_url in page.url


def test_calendar_workbench_real_browser_prepare_cancel_publish_and_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the real shell can carry a safe preview into explicit publication."""

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    publisher = _create_browser_publisher()
    _install_actual_calendar_runtime(monkeypatch)
    console_messages: list[str] = []
    page_errors: list[str] = []
    bundle_responses: list[Any] = []
    action_post_confirmations: list[tuple[str, bool | None]] = []

    with _serve_local_django() as base_url:
        with _playwright_subprocess_event_loop_policy(), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                admin_context = browser.new_context(viewport={"width": 1440, "height": 1000})
                admin_page = admin_context.new_page()
                admin_page.on("console", lambda message: console_messages.append(message.text))
                admin_page.on("pageerror", lambda error: page_errors.append(str(error)))
                admin_page.on("response", lambda response: bundle_responses.append(response))

                def collect_action_post(request: Any) -> None:
                    """Record endpoint and confirmation bit, never request parameters."""

                    path = urlsplit(request.url).path
                    if request.method == "POST" and path.startswith("/api/tui/actions/"):
                        payload = request.post_data_json
                        confirmed = payload.get("confirmed") if isinstance(payload, dict) else None
                        action_post_confirmations.append(
                            (path, confirmed if type(confirmed) is bool else None)
                        )

                admin_page.on("request", collect_action_post)
                _login_through_form(
                    admin_page,
                    base_url=base_url,
                    username=publisher.username,
                )
                _assert_served_bundle_matches_source(
                    page=admin_page,
                    base_url=base_url,
                    responses=bundle_responses,
                )
                _open_calendar_screen(admin_page)

                scope_response = _run_read_action(admin_page, "scope")
                scope_payload = scope_response.json()
                blocked_scope = scope_payload.get("view_model", {})
                assert blocked_scope.get("status") == "配置不可用"
                assert "未能确定唯一可用的日历配置" in blocked_scope.get("message", "")
                assert _run_database_call(_source_counts) == (0, 0)
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                _main_panel(admin_page).locator(".tui-view-status").get_by_text(
                    "配置不可用", exact=False
                ).wait_for(state="visible")

                responses = _run_database_call(
                    _install_source,
                    monkeypatch,
                    (_calendar_body(), _calendar_body()),
                )
                selected_response = _run_read_action(admin_page, "scope")
                selected = selected_response.json().get("view_model", {})
                assert selected.get("status") == "已读取配置元数据"
                assert "来源响应最大有效期" in selected.get("message", "")
                assert "凭据、数据源运行状态和当前发布状态尚未检查" in selected.get("message", "")
                assert _run_database_call(_source_counts) == (0, 0)
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                _main_panel(admin_page).locator(".tui-view-status").get_by_text(
                    "已读取配置元数据", exact=False
                ).wait_for(state="visible")

                current_form = _action_form(admin_page, "current")
                current_form.locator('[name="exchange"]').fill("SSE")
                _run_read_action(admin_page, "current")
                _main_panel(admin_page).locator(".tui-view-status").get_by_text(
                    "无当前版本", exact=False
                ).wait_for(state="visible")
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)

                prepare_form = _action_form(admin_page, "prepare")
                prepare_form.locator('[name="exchange"]').fill("SSE")
                prepare_form.locator('[name="coverage_start"]').fill("2026-10-15")
                prepare_form.locator('[name="coverage_end"]').fill("2026-10-16")
                prepare_form.locator('button[type="submit"]').click()
                prepare_modal = admin_page.locator("[data-tui-modal]")
                try:
                    prepare_modal.wait_for(state="visible", timeout=5000)
                except PlaywrightTimeoutError as error:
                    raise AssertionError(
                        {
                            "phase": "first_prepare_preflight_before_capture",
                            "page_errors": page_errors,
                            "action_confirmations": action_post_confirmations,
                            "visible_result": _main_panel(admin_page).inner_text(),
                        }
                    ) from error
                assert _run_database_call(_source_counts) == (0, 0)
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                prepare_modal.locator("[data-cancel-action]").click()
                prepare_modal.wait_for(state="hidden")
                assert _confirmed_action_count(action_post_confirmations, "prepare") == 0
                assert _run_database_call(_source_counts) == (0, 0)

                preview_response = _run_confirmed_action(admin_page, "prepare")
                preview_token = _extract_confirmation_token(preview_response)
                assert len(responses) == 1
                assert _run_database_call(_source_counts) == (1, 1)
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                _main_panel(admin_page).locator(".tui-view-status").get_by_text(
                    "预览已准备", exact=False
                ).wait_for(state="visible")
                _assert_token_not_exposed(admin_page, preview_token, console=console_messages)

                confirm_form = _action_form(admin_page, "confirm")
                confirm_form.locator('button[type="submit"]').click()
                publish_modal = admin_page.locator("[data-tui-modal]")
                publish_modal.wait_for(state="visible")
                publish_modal.locator("[data-confirm-action]").wait_for(state="visible")
                admin_page.keyboard.press("Escape")
                publish_modal.wait_for(state="hidden")
                assert _confirmed_action_count(action_post_confirmations, "confirm") == 0
                confirm_form.locator('button[type="submit"]').click()
                _main_panel(admin_page).get_by_text("需要重新准备", exact=False).wait_for(
                    state="visible"
                )
                assert _confirmed_action_count(action_post_confirmations, "confirm") == 0
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                _assert_token_not_exposed(admin_page, preview_token, console=console_messages)

                prepare_form = _action_form(admin_page, "prepare")
                prepare_form.locator('[name="exchange"]').fill("SSE")
                prepare_form.locator('[name="coverage_start"]').fill("2026-10-15")
                prepare_form.locator('[name="coverage_end"]').fill("2026-10-16")
                new_preview_response = _run_confirmed_action(admin_page, "prepare")
                new_preview_token = _extract_confirmation_token(new_preview_response)
                assert new_preview_token != preview_token
                assert len(responses) == 2
                assert _run_database_call(_source_counts) == (2, 2)
                assert _run_database_call(_formal_counts) == (0, 0, 0, 0, 0, 0)
                _assert_token_not_exposed(admin_page, new_preview_token, console=console_messages)

                final_publish_response = _run_confirmed_action(admin_page, "confirm")
                assert final_publish_response.status == 200
                assert _confirmed_action_count(action_post_confirmations, "confirm") == 1
                _main_panel(admin_page).locator(".tui-view-status").get_by_text(
                    "日历已首次发布", exact=False
                ).wait_for(state="visible")
                assert _run_database_call(_formal_counts) == (1, 1, 1, 1, 1, 1)

                def revoke_publish_permission() -> None:
                    """Remove only the fixture publisher's Calendar grant."""

                    permission = publisher.user_permissions.get(
                        codename="publish_exchange_calendar",
                        content_type__app_label="data_center",
                    )
                    publisher.user_permissions.remove(permission)

                _run_database_call(revoke_publish_permission)

                current_form = _action_form(admin_page, "current")
                current_form.locator('[name="exchange"]').fill("SSE")
                _run_read_action(admin_page, "current")
                main_panel = _main_panel(admin_page)
                calendar_dates = main_panel.locator("tbody tr td:first-child")
                calendar_dates.get_by_text("2026-10-15", exact=True).wait_for(state="visible")
                calendar_dates.get_by_text("2026-10-16", exact=True).wait_for(state="visible")
                main_panel.get_by_text("开市", exact=True).wait_for(state="visible")
                main_panel.get_by_text("休市", exact=True).wait_for(state="visible")
                main_panel.get_by_text("不可用于交易或投资决策", exact=False).wait_for(
                    state="visible"
                )
                admin_page.set_viewport_size({"width": 390, "height": 844})
                calendar_dates.get_by_text("2026-10-15", exact=True).wait_for(state="visible")
                main_panel.get_by_text("不可用于交易或投资决策", exact=False).wait_for(
                    state="visible"
                )
                assert admin_page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                admin_page.set_viewport_size({"width": 1440, "height": 1000})
                assert _run_database_call(_source_counts) == (2, 2)
                assert _run_database_call(_formal_counts) == (1, 1, 1, 1, 1, 1)
                _assert_token_not_exposed(admin_page, new_preview_token, console=console_messages)
                _run_database_call(
                    _assert_continuation_is_not_audited,
                    [preview_token, new_preview_token],
                )
                assert all(response.response.closed for response in responses)

                regular = _run_database_call(
                    _create_browser_regular_user,
                    approved_by=publisher,
                )
                regular_context = browser.new_context(viewport={"width": 1280, "height": 900})
                regular_page = regular_context.new_page()
                _login_through_form(
                    regular_page,
                    base_url=base_url,
                    username=regular.username,
                )
                regular_location = regular_page.locator("#tui-location-input")
                regular_location.fill(_SCREEN_KEY)
                regular_location.press("Enter")
                _main_panel(regular_page).get_by_text("无权访问", exact=False).wait_for(
                    state="visible"
                )
                assert _action_form(regular_page, "prepare").count() == 0
                assert _run_database_call(_source_counts) == (2, 2)
                assert _run_database_call(_formal_counts) == (1, 1, 1, 1, 1, 1)
                regular_context.close()
                admin_context.close()
            finally:
                browser.close()

    assert not page_errors
    assert all("encrypted:v1:" not in message for message in console_messages)
    write_paths = {
        f"/api/tui/actions/{_ACTION_PREFIX}{suffix}/run/" for suffix in ("prepare", "confirm")
    }
    assert all(
        confirmed is not None
        for path, confirmed in action_post_confirmations
        if path in write_paths
    )
