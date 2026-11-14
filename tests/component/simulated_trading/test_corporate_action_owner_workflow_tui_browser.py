"""Ordinary-owner TUI journeys over explicitly synthetic corporate-action sources."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import playwright.sync_api as playwright_api
import pytest
from django.conf import settings
from django.db import connection
from django.middleware.csrf import _does_token_match
from django.test import override_settings
from playwright.sync_api import Route, expect, sync_playwright

from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel
from tests.component.simulated_trading.test_corporate_action_owner_workflow_http_postgres import (
    _WORKFLOW_URLCONF,
    _business_effect_counts,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
    recover_owner_workflow_operator_authority,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=(*ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS, "django.contrib.staticfiles"),
)

_SCREEN = "execution.corporate-actions"
_ACCOUNT_SCREEN = "execution.accounts"
_WORKFLOW_PREFIX = "simulated-trading.corporate-action-workflow-"
_CONSENT_PREFIX = "simulated-trading.corporate-action-consent-"
_PREPARE_ACTION = _WORKFLOW_PREFIX + "prepare"
_CONFIRM_ACTION = _WORKFLOW_PREFIX + "confirm"
_REFRESH_ACTION = _WORKFLOW_PREFIX + "refresh"
_EVENTS_ACTION = _WORKFLOW_PREFIX + "events"
_AUDIT_ACTION = _WORKFLOW_PREFIX + "audit-receipts"
_CONSENT_PREPARE_ACTION = _CONSENT_PREFIX + "prepare"
_CONSENT_CONFIRM_ACTION = _CONSENT_PREFIX + "confirm"
_CONSENT_WITHDRAW_PREPARE_ACTION = _CONSENT_PREFIX + "withdraw-prepare"
_CONSENT_WITHDRAW_ACTION = _CONSENT_PREFIX + "withdraw"
_CONSENT_FIELDS = (
    "cash_dividend",
    "tax_assessment",
    "tax_withholding",
    "share_distribution",
    "rights_not_exercised",
)
_EXPECTED_EFFECTS = {
    "cash_entitlement": (1, 0, 0, 1, 1),
    "cash_payment": (1, 0, 0, 1, 1),
    "tax_assess": (0, 1, 0, 1, 1),
    "tax_recognize": (0, 0, 1, 1, 1),
    "tax_collect": (0, 0, 1, 1, 1),
    "share_entitlement": (1, 0, 0, 1, 1),
    "share_delivery": (1, 0, 0, 1, 1),
    "share_sellable_release": (1, 0, 0, 1, 1),
    "rights_not_exercised": (1, 0, 0, 1, 1),
}


@pytest.fixture(autouse=True)
def _loopback_http_browser_settings() -> Iterator[None]:
    """Keep real Session/CSRF checks while allowing the isolated HTTP browser socket."""
    with override_settings(
        ALLOWED_HOSTS=["127.0.0.1", "localhost", "testserver"],
        CSRF_COOKIE_SECURE=False,
        SECURE_SSL_REDIRECT=False,
        SESSION_COOKIE_SECURE=False,
    ):
        yield


@contextmanager
def _ordinary_owner_browser(
    world: OwnerWorkflowNativeWorld, *, live_server: Any
) -> Iterator[tuple[Any, Any, dict[str, Any]]]:
    """Open a real browser session using only the owner's existing Session and CSRF cookies."""
    session_cookie = world.owner.client.cookies.get(settings.SESSION_COOKIE_NAME)
    csrf_cookie = world.owner.client.cookies.get(settings.CSRF_COOKIE_NAME)
    if not (session_cookie is not None and csrf_cookie is not None):
        raise AssertionError("the owner fixture did not issue browser Session and CSRF cookies")
    try:
        csrf_matches = _does_token_match(world.owner.csrf_token, csrf_cookie.value)
    except (AssertionError, IndexError, ValueError):
        csrf_matches = False
    if not csrf_matches:
        raise AssertionError("the browser CSRF cookie did not match")

    state: dict[str, Any] = {
        "base_url": live_server.url,
        "console_pending": [],
        "console_token_leaks": [],
        "continuation_secrets": [],
        "page_errors": 0,
        "nonlocal_paths": [],
        "action_responses": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie.value,
                    "url": live_server.url,
                },
                {
                    "name": settings.CSRF_COOKIE_NAME,
                    "value": csrf_cookie.value,
                    "url": live_server.url,
                },
            ]
        )

        def local_only(route: Route) -> None:
            """Keep the browser journey on the assigned loopback Django server."""
            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                state["nonlocal_paths"].append(target.path)
                route.abort("blockedbyclient")
                return
            route.continue_()

        context.route("**/*", local_only)

        def watch_page(page: Any) -> None:
            """Record only action paths/statuses and keep console contents out of diagnostics."""

            def observe_console(message: Any) -> None:
                text = message.text
                if any(secret in text for secret in state["continuation_secrets"]):
                    state["console_token_leaks"].append(True)
                else:
                    state["console_pending"].append(text)

            def observe_response(response: Any) -> None:
                path = urlsplit(response.url).path
                if path.startswith("/api/tui/actions/"):
                    state["action_responses"].append((path, int(response.status)))

            page.on("console", observe_console)
            page.on("pageerror", lambda _error: state.__setitem__("page_errors", 1))
            page.on("response", observe_response)
            page.set_default_timeout(180_000)
            page.set_default_navigation_timeout(180_000)

        page = context.new_page()
        watch_page(page)
        try:
            _open_owner_workflow(page, base_url=live_server.url)
            yield context, page, state
        except (AssertionError, playwright_api.Error):
            configured = os.environ.get("ASH05_BROWSER_EVIDENCE_DIR")
            if configured:
                directory = Path(configured)
                directory.mkdir(parents=True, exist_ok=True)
                # Record structure only: no cookies, values, bodies or token text.
                inventory = page.evaluate("""() => ({
                    panels: Array.from(document.querySelectorAll('[data-dashboard-panel]')).map(e => e.dataset.dashboardPanel),
                    forms: Array.from(document.querySelectorAll('form[data-action-ui-key]')).map(e => ({key: e.dataset.actionUiKey, visible: Boolean(e.getClientRects().length)})),
                    opens: Array.from(document.querySelectorAll('[data-dashboard-open]')).map(e => ({action: e.dataset.dashboardAction, visible: Boolean(e.getClientRects().length)})),
                    details: Array.from(document.querySelectorAll('details.tui-panel-disclosure')).map(e => ({panel: e.closest('[data-dashboard-panel]')?.dataset.dashboardPanel, open: e.open}))
                })""")
                (directory / f"failure-ui-{world.account_id}.json").write_text(
                    json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            raise
        finally:
            context.close()
            browser.close()


def _open_owner_workflow(page: Any, *, base_url: str) -> None:
    """Enter the workflow through its visible account-screen navigation entry."""
    page.goto(
        f"{base_url}/tui/?screen={_ACCOUNT_SCREEN}",
        wait_until="networkidle",
        timeout=180_000,
    )
    entry = page.locator(
        '[data-dashboard-panel="corporate-actions-entry"] '
        f'[data-dashboard-open][data-dashboard-target="{_SCREEN}"]'
    )
    expect(entry).to_be_visible(timeout=180_000)
    entry.click()
    expect(page.locator('[data-dashboard-panel="corporate-action-workflow-events"]')).to_be_visible(
        timeout=180_000
    )


def _action_ui_key(action_key: str) -> str:
    """Match the stable task-form key emitted from a TUI action identifier."""
    digest = hashlib.sha1(action_key.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"task-{digest}"


def _dashboard_form(page: Any, panel_key: str, action_key: str) -> Any:
    """Use an inline form or the exact published panel header to open this task."""
    panel = page.locator(f'[data-dashboard-panel="{panel_key}"]')
    if panel.count() == 0:
        workspace_return = page.locator("[data-return-dashboard-workspace]")
        expect(workspace_return).to_be_visible(timeout=180_000)
        workspace_return.click()
        expect(panel).to_be_visible(timeout=180_000)
    details = panel.locator("details.tui-panel-disclosure")
    if details.count() == 1 and not details.evaluate("element => element.open"):
        details.locator("summary").click()
    panel_form = panel.locator(f'form[data-action-ui-key="{_action_ui_key(action_key)}"]')
    if panel_form.count() == 1 and panel_form.is_visible():
        return panel_form
    # Header and initial prompt can both contain this action. The header is
    # unique and remains available after the panel body displays a result.
    open_action = panel.locator(
        f'button.tui-dashboard-open[data-dashboard-open][data-dashboard-action="{action_key}"]'
    )
    expect(open_action).to_be_visible(timeout=180_000)
    open_action.click()
    task_form = page.locator(
        f'[data-actions-panel] form[data-action-ui-key="{_action_ui_key(action_key)}"]'
    )
    expect(task_form).to_be_visible(timeout=180_000)
    return task_form


def _workflow_result_container(page: Any, panel_key: str) -> Any:
    """Read the visible targeted panel or the normal standalone task result."""
    panel = page.locator(f'[data-dashboard-panel="{panel_key}"]')
    if panel.count() == 1 and panel.is_visible():
        return panel
    main = page.locator("[data-main-panel]")
    expect(main).to_be_visible(timeout=180_000)
    return main


def _open_consent_prepare_form(page: Any) -> Any:
    """Open consent through its visible published supporting panel action."""
    return _dashboard_form(page, "corporate-action-consent-result", _CONSENT_PREPARE_ACTION)


def _set_fields(form: Any, values: dict[str, object]) -> None:
    """Fill only the explicit fields declared by the current TUI action metadata."""
    for key, value in values.items():
        field = form.locator(f'[name="{key}"]')
        assert field.count(), "a published workflow field is missing"
        input_type = field.get_attribute("type")
        if input_type == "checkbox":
            field.check() if value is True else field.uncheck()
        elif field.evaluate("element => element.tagName === 'SELECT'"):
            field.select_option(str(value))
        else:
            field.fill(str(value))


def _action_run_path(action_key: str) -> str:
    """Return the local wrapper route for one published TUI action."""
    return f"/api/tui/actions/{action_key}/run/"


def _response_payload(response: Any) -> dict[str, Any]:
    """Decode a successful JSON response without including its body in failures."""
    if not (response.status == 200):
        raise AssertionError("the local TUI action wrapper did not return HTTP 200")
    content_type = str(response.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    if not (content_type == "application/json"):
        raise AssertionError("the TUI wrapper did not return JSON content")
    payload = response.json()
    if not (isinstance(payload, dict)):
        raise AssertionError("the local TUI action wrapper returned a non-object payload")
    return payload


def _expect_action_success(payload: dict[str, Any]) -> None:
    """Require a successful TUI transport and successful underlying owner operation."""
    response = payload.get("response")
    if (
        payload.get("outcome") != "success"
        or not isinstance(response, dict)
        or response.get("status_code") != 200
    ):
        raise AssertionError("the ordinary-owner TUI action did not complete successfully")


def _run_dashboard_action(
    page: Any,
    *,
    panel_key: str,
    action_key: str,
    fields: dict[str, object],
    confirm_in_modal: bool = False,
) -> dict[str, Any]:
    """Submit a visible dashboard action and wait for its real local wrapper response."""
    form = _dashboard_form(page, panel_key, action_key)
    _set_fields(form, fields)
    expected_path = _action_run_path(action_key)
    if confirm_in_modal:
        form.locator(".tui-action-submit").click()
        modal = page.locator("[data-tui-modal]")
        expect(modal).to_be_visible(timeout=180_000)
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path == expected_path,
            timeout=180_000,
        ) as action_response:
            modal.locator("[data-confirm-action]").click()
    else:
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path == expected_path,
            timeout=180_000,
        ) as action_response:
            form.locator(".tui-action-submit").click()
    return _response_payload(action_response.value)


def _refresh_account(
    page: Any, world: OwnerWorkflowNativeWorld, *, has_financial_history: bool
) -> None:
    """Use test-operator recovery only as fixture setup, then run the ordinary TUI refresh."""
    if has_financial_history:
        # This independent fixture operator renewal is not an ordinary-owner action or grant.
        recover_owner_workflow_operator_authority(world)
    result = _run_dashboard_action(
        page,
        panel_key="corporate-action-workflow-refresh",
        action_key=_REFRESH_ACTION,
        fields={"account_id": world.account_id, "confirmed": "true"},
        confirm_in_modal=True,
    )
    _expect_action_success(result)


def _select_consent(
    page: Any,
    world: OwnerWorkflowNativeWorld,
    *,
    capabilities: tuple[str, ...],
    state: dict[str, Any],
) -> None:
    """Explicitly select the requested least-capability subset and confirm its continuation."""
    selected = set(capabilities)
    assert selected and selected.issubset(_CONSENT_FIELDS), "consent selection is outside V3"
    form = _open_consent_prepare_form(page)
    _set_fields(
        form,
        {
            "account_id": world.account_id,
            **{field: field in selected for field in _CONSENT_FIELDS},
        },
    )
    actual_selection = {
        field for field in _CONSENT_FIELDS if form.locator(f'[name="{field}"]').is_checked()
    }
    assert actual_selection == selected, "the consent form did not preserve the exact subset"
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == _action_run_path(_CONSENT_PREPARE_ACTION),
        timeout=180_000,
    ) as prepared_response:
        form.locator(".tui-action-submit").click()
    prepared = _response_payload(prepared_response.value)
    _expect_action_success(prepared)
    token = _continuation_token(
        prepared,
        expected_action=_CONSENT_CONFIRM_ACTION,
        token_field="consent_token",
    )
    _assert_secret_not_exposed(page, token, state=state)
    result = _confirm_continuation(
        page,
        panel_key="corporate-action-consent-result",
        target_action=_CONSENT_CONFIRM_ACTION,
        token=token,
        state=state,
    )
    _expect_action_success(result)


def _prepare_workflow_intent(
    page: Any,
    world: OwnerWorkflowNativeWorld,
    *,
    action: str,
    state: dict[str, Any],
    settlement_date: date | None = None,
) -> str:
    """Prepare one event-row action using only event, operation, and optional settlement date."""
    _load_event_row(page, world)
    event_panel = _workflow_result_container(page, "corporate-action-workflow-events")
    event_row = event_panel.locator("tbody tr").filter(has_text=world.capture.title)
    row_action = event_row.locator(
        "[data-dashboard-row-action]" f'[data-row-action-key="{_PREPARE_ACTION}"]'
    )
    expect(row_action).to_be_visible(timeout=180_000)
    row_action.click()
    form = page.locator(
        "[data-tui-modal] " f'form[data-action-ui-key="{_action_ui_key(_PREPARE_ACTION)}"]'
    )
    expect(form).to_be_visible(timeout=180_000)
    assert form.locator('[name="account_id"]').input_value() == str(world.account_id)
    assert form.locator('[name="event_id"]').input_value() == _event_id_from_row(event_row)
    form.locator('[name="action"]').select_option(action)
    if settlement_date is not None:
        form.locator('[name="settlement_date"]').fill(settlement_date.isoformat())
    expected_path = _action_run_path(_PREPARE_ACTION)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path,
        timeout=180_000,
    ) as prepared_response:
        form.locator(".tui-action-submit").click()
    prepared = _response_payload(prepared_response.value)
    _expect_action_success(prepared)
    token = _continuation_token(
        prepared,
        expected_action=_CONFIRM_ACTION,
        token_field="continuation_token",
    )
    _assert_secret_not_exposed(page, token, state=state)
    return token


def _event_id_from_row(event_row: Any) -> str:
    """Read the visible event identifier bound into the row-action form."""
    params_text = event_row.locator(
        "[data-dashboard-row-action]" f'[data-row-action-key="{_PREPARE_ACTION}"]'
    ).get_attribute("data-row-action-params")
    try:
        params = json.loads(params_text or "")
    except json.JSONDecodeError as error:
        raise AssertionError(
            "the visible event row has no valid bound action parameters"
        ) from error
    event_id = params.get("event_id") if isinstance(params, dict) else None
    assert type(event_id) is str and event_id, "the event row has no stable source identifier"
    return event_id


def _load_event_row(page: Any, world: OwnerWorkflowNativeWorld) -> str:
    """Read the current owner-scoped event table through its visible dashboard form."""
    result = _run_dashboard_action(
        page,
        panel_key="corporate-action-workflow-events",
        action_key=_EVENTS_ACTION,
        fields={"account_id": world.account_id},
    )
    _expect_action_success(result)
    view_model = result.get("view_model")
    if not (isinstance(view_model, dict) and view_model.get("status") == "已读取"):
        raise AssertionError("the event listing did not return its visible read result")
    event_panel = _workflow_result_container(page, "corporate-action-workflow-events")
    event_row = event_panel.locator("tbody tr").filter(has_text=world.capture.title)
    expect(event_row).to_have_count(1, timeout=180_000)
    expect(event_row).to_contain_text(world.asset_code)
    expect(event_row).to_contain_text("待核对原文与当前窗口")
    return _event_id_from_row(event_row)


def _continuation_token(payload: dict[str, Any], *, expected_action: str, token_field: str) -> str:
    """Extract one protected continuation into test memory without rendering or logging it."""
    continuation = payload.get("continuation")
    if not (isinstance(continuation, dict) and continuation.get("action_key") == expected_action):
        raise AssertionError("The protected continuation shape is invalid")
    inputs = continuation.get("input")
    if not (isinstance(inputs, dict) and set(inputs) == {"account_id", token_field}):
        raise AssertionError("The protected continuation shape is invalid")
    token = inputs.get(token_field)
    if not (type(token) is str and token):
        raise AssertionError("The protected continuation shape is invalid")
    return token


def _confirm_continuation(
    page: Any,
    *,
    panel_key: str,
    target_action: str,
    token: str,
    state: dict[str, Any],
    cancel: bool = False,
    expect_revoked: bool = False,
) -> dict[str, Any] | None:
    """Drive the TUI's 409 preflight, then either cancel or explicitly confirm the action."""
    result_container = _workflow_result_container(page, panel_key)
    button = result_container.locator('[data-result-continuation="true"] button')
    expect(button).to_be_visible(timeout=180_000)
    expected_path = _action_run_path(target_action)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path,
        timeout=180_000,
    ) as preflight_response:
        button.click()
    preflight = _response_payload(preflight_response.value)
    nested = preflight.get("response")
    if (
        preflight.get("confirmation_required") is not True
        or not isinstance(nested, dict)
        or nested.get("status_code") != 409
    ):
        raise AssertionError("continuation did not stop at the expected HTTP 409 confirmation gate")
    _assert_secret_not_exposed(page, token, state=state)
    modal = page.locator("[data-tui-modal]")
    expect(modal).to_be_visible(timeout=180_000)
    if cancel:
        modal.locator("[data-cancel-action]").click()
        expect(modal).to_be_hidden(timeout=180_000)
        _assert_secret_not_exposed(page, token, state=state)
        return None
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == expected_path,
        timeout=180_000,
    ) as confirmed_response:
        modal.locator("[data-confirm-action]").click()
    confirmed = _response_payload(confirmed_response.value)
    _assert_secret_not_exposed(page, token, state=state)
    nested = confirmed.get("response")
    status_code = nested.get("status_code") if isinstance(nested, dict) else None
    if expect_revoked:
        view_model = confirmed.get("view_model")
        if status_code == 200:
            if (
                confirmed.get("outcome") != "blocked"
                or confirmed.get("blocking_reason")
                != "CORPORATE_ACTION_SELECTED_CAPABILITY_REQUIRED"
                or (not isinstance(view_model, dict))
                or (view_model.get("status") != "不可用于决策")
                or (not confirmed.get("business_summary"))
            ):
                raise AssertionError(
                    "withdrawn consent did not produce the stable visible capability block"
                )
            expect(_workflow_result_container(page, panel_key)).to_contain_text(
                "本次尚未办理", timeout=180_000
            )
        elif status_code == 403:
            if (
                confirmed.get("outcome") == "success"
                or not isinstance(view_model, dict)
                or view_model.get("status") != "错误"
                or (
                    "当前会话无权操作该模拟账户。"
                    not in str(confirmed.get("business_summary") or "")
                )
            ):
                raise AssertionError(
                    "withdrawn consent did not produce a visible authorization block"
                )
            expect(_workflow_result_container(page, panel_key)).to_contain_text(
                "当前会话无权操作该模拟账户", timeout=180_000
            )
        else:
            raise AssertionError("withdrawn consent failed for an unrelated reason")
    else:
        _expect_action_success(confirmed)
    return confirmed


def _assert_secret_not_exposed(page: Any, secret: str, *, state: dict[str, Any]) -> None:
    """Check browser-visible state and console while retaining no diagnostic text on failure."""
    exposed = _browser_state_contains(page, secret)
    pending = state["console_pending"]
    console_leak = any(secret in message for message in pending)
    pending.clear()
    state["continuation_secrets"].append(secret)
    state["console_token_leaks"].append(console_leak)
    if exposed or console_leak:
        raise AssertionError("a continuation secret was exposed to browser state")


def _browser_state_contains(page: Any, secret: str) -> bool:
    """Search page/URL/input/storage state and discard the inspected serialization immediately."""
    state_text = page.evaluate("""() => JSON.stringify({
            html: document.documentElement.outerHTML,
            text: document.body.innerText,
            url: window.location.href,
            inputs: Array.from(document.querySelectorAll('input, textarea, select')).map(node => node.value),
            local: Array.from({length: localStorage.length}, (_, i) => {
                const key = localStorage.key(i); return [key, key === null ? null : localStorage.getItem(key)];
            }),
            session: Array.from({length: sessionStorage.length}, (_, i) => {
                const key = sessionStorage.key(i); return [key, key === null ? null : sessionStorage.getItem(key)];
            })
        })""")
    found = secret in state_text
    del state_text
    return found


def _assert_browser_clean(state: dict[str, Any]) -> None:
    """Fail on browser errors, external traffic, or any previously scanned console secret."""
    pending = state["console_pending"]
    console_leak = any(
        secret in message for secret in state["continuation_secrets"] for message in pending
    )
    pending.clear()
    if (
        state["page_errors"]
        or state["nonlocal_paths"]
        or console_leak
        or any(state["console_token_leaks"])
    ):
        raise AssertionError("the local ordinary-owner browser journey was not clean")


def _replay_same_tui_confirmation(
    context: Any,
    page: Any,
    *,
    base_url: str,
    csrf_token: str,
    world: OwnerWorkflowNativeWorld,
    token: str,
    state: dict[str, Any],
) -> None:
    """Replay the exact confirmed TUI wrapper request with the same signed continuation."""
    response = context.request.post(
        f"{base_url}{_action_run_path(_CONFIRM_ACTION)}",
        data={
            "params": {
                "account_id": str(world.account_id),
                "continuation_token": token,
                "confirmed": True,
            },
            "confirmed": True,
        },
        headers={
            "X-CSRFToken": csrf_token,
            "Origin": base_url,
            "Referer": f"{base_url}/tui/",
        },
        timeout=180_000,
    )
    if not (response.status == 200):
        raise AssertionError("the same TUI confirmation did not return HTTP 200 on replay")
    payload = response.json()
    if not (isinstance(payload, dict)):
        raise AssertionError("the TUI confirmation replay returned a non-object response")
    _expect_action_success(payload)
    _assert_secret_not_exposed(page, token, state=state)


def _assert_effect_delta(
    before: tuple[int, int, int, int, int],
    after: tuple[int, int, int, int, int],
    expected: tuple[int, int, int, int, int],
) -> None:
    """Require the exact simulated ledger/header/operation/Audit/Outbox increment."""
    delta = tuple(current - original for original, current in zip(before, after, strict=True))
    assert delta == expected, "the corporate-action operation produced an unexpected effect set"


def _read_receipts(page: Any, world: OwnerWorkflowNativeWorld, labels: tuple[str, ...]) -> None:
    """Read original user-visible Audit receipts from the published workflow panel."""
    result = _run_dashboard_action(
        page,
        panel_key="corporate-action-workflow-audit-receipts",
        action_key=_AUDIT_ACTION,
        fields={"account_id": world.account_id},
    )
    _expect_action_success(result)
    panel = _workflow_result_container(page, "corporate-action-workflow-audit-receipts")
    expect(panel).to_be_visible(timeout=180_000)
    for label in labels:
        expect(panel).to_contain_text(label, timeout=180_000)


def _save_screenshot_if_configured(page: Any, filename: str) -> None:
    """Write only an optional nonsensitive screenshot under the assigned evidence directory."""
    configured = os.environ.get("ASH05_BROWSER_EVIDENCE_DIR")
    if not configured:
        return
    directory = Path(configured).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(directory / filename), full_page=True, timeout=180_000)


def test_nonstaff_owner_completes_cash_payment_and_tax_from_the_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live_server: Any,
) -> None:
    """Complete all five synthetic cash/tax operations with visible per-stage consent."""
    if connection.vendor != "postgresql":
        pytest.skip("the migrated ordinary-owner browser journey runs only on assigned PostgreSQL")
    with isolated_task_channels(), override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        starting_account = SimulatedAccountModel.objects.get(pk=world.account_id)
        starting_cash = starting_account.current_cash
        assert not (
            starting_account.cash_known is not True
            or starting_account.cash_reconciliation_status != "simulated_ledger"
            or type(starting_cash) is not Decimal
            or not starting_cash.is_finite()
        ), "the initial account cash is not a known simulated-ledger value"
        with _ordinary_owner_browser(world, live_server=live_server) as (context, page, state):
            _refresh_account(page, world, has_financial_history=False)
            _select_consent(
                page,
                world,
                capabilities=("cash_dividend", "tax_assessment", "tax_withholding"),
                state=state,
            )
            event_id = _load_event_row(page, world)

            cancelled_baseline = _business_effect_counts(world.account_id)
            cancelled_token = _prepare_workflow_intent(
                page, world, action="cash_entitlement", state=state
            )
            _confirm_continuation(
                page,
                panel_key="corporate-action-workflow-result",
                target_action=_CONFIRM_ACTION,
                token=cancelled_token,
                state=state,
                cancel=True,
            )
            assert (
                _business_effect_counts(world.account_id) == cancelled_baseline
            ), "canceling the workflow confirmation changed financial effects"

            before = _business_effect_counts(world.account_id)
            entitlement_token = _prepare_workflow_intent(
                page, world, action="cash_entitlement", state=state
            )
            _confirm_continuation(
                page,
                panel_key="corporate-action-workflow-result",
                target_action=_CONFIRM_ACTION,
                token=entitlement_token,
                state=state,
            )
            after_entitlement = _business_effect_counts(world.account_id)
            _assert_effect_delta(before, after_entitlement, _EXPECTED_EFFECTS["cash_entitlement"])
            _replay_same_tui_confirmation(
                context,
                page,
                base_url=live_server.url,
                csrf_token=world.owner.csrf_token,
                world=world,
                token=entitlement_token,
                state=state,
            )
            assert (
                _business_effect_counts(world.account_id) == after_entitlement
            ), "the signed entitlement retry duplicated a financial effect"
            entitlement = CorporateActionPostingModel.objects.get(
                account_id=world.account_id,
                source_event_id=event_id,
                stage="cash_entitlement",
                entry_kind="posting",
            )
            assert not (
                entitlement.eligible_quantity != Decimal("100.000000")
                or entitlement.cash_amount != Decimal("20.00")
                or entitlement.cash_delta != Decimal("0.00")
                or entitlement.cash_receivable_delta != Decimal("20.00")
            ), "cash entitlement did not preserve the synthetic record-date facts"
            account_after_entitlement = SimulatedAccountModel.objects.get(pk=world.account_id)
            assert not (
                account_after_entitlement.cash_known is not True
                or account_after_entitlement.current_cash != starting_cash
            ), "cash entitlement changed known cash before payment"

            _refresh_account(page, world, has_financial_history=True)
            _select_consent(
                page,
                world,
                capabilities=("cash_dividend", "tax_assessment", "tax_withholding"),
                state=state,
            )
            before = _business_effect_counts(world.account_id)
            payment_token = _prepare_workflow_intent(
                page, world, action="cash_payment", state=state
            )
            _confirm_continuation(
                page,
                panel_key="corporate-action-workflow-result",
                target_action=_CONFIRM_ACTION,
                token=payment_token,
                state=state,
            )
            _assert_effect_delta(
                before,
                _business_effect_counts(world.account_id),
                _EXPECTED_EFFECTS["cash_payment"],
            )
            payment_row = CorporateActionPostingModel.objects.get(
                account_id=world.account_id,
                source_event_id=event_id,
                stage="cash_payment",
                entry_kind="posting",
            )
            assert not (
                payment_row.cash_delta != entitlement.cash_amount
                or payment_row.cash_receivable_delta != -entitlement.cash_amount
            ), "cash payment did not exactly settle the original receivable"
            account = SimulatedAccountModel.objects.get(pk=world.account_id)
            after_payment_cash = account.current_cash
            assert account.cash_known is True and type(after_payment_cash) is Decimal
            assert (
                after_payment_cash == starting_cash + entitlement.cash_amount
            ), "the synthetic cash payment did not match its entitlement"

            withholding_amount: Decimal | None = None
            for action in ("tax_assess", "tax_recognize", "tax_collect"):
                _refresh_account(page, world, has_financial_history=True)
                _select_consent(
                    page,
                    world,
                    capabilities=("cash_dividend", "tax_assessment", "tax_withholding"),
                    state=state,
                )
                before = _business_effect_counts(world.account_id)
                token = _prepare_workflow_intent(
                    page,
                    world,
                    action=action,
                    state=state,
                    settlement_date=world.settlement_date,
                )
                _confirm_continuation(
                    page,
                    panel_key="corporate-action-workflow-result",
                    target_action=_CONFIRM_ACTION,
                    token=token,
                    state=state,
                )
                _assert_effect_delta(
                    before, _business_effect_counts(world.account_id), _EXPECTED_EFFECTS[action]
                )
                account.refresh_from_db()
                if action == "tax_assess":
                    assessment = CorporateActionTaxAssessmentHeaderModel.objects.get(
                        account_id=world.account_id,
                        source_event_id=event_id,
                        settlement_date=world.settlement_date,
                    )
                    try:
                        withholding_amount = Decimal(assessment.withholding_amount_text)
                    except InvalidOperation as error:
                        raise AssertionError(
                            "the assessed tax amount is not exact decimal text"
                        ) from error
                    assert withholding_amount.is_finite() and withholding_amount > 0
                    assert (
                        account.current_cash == after_payment_cash
                    ), "tax assessment unexpectedly changed account cash"
                    continue

                liabilities_now = list(
                    CorporateActionTaxLiabilityOperationModel.objects.filter(
                        account_id=world.account_id
                    ).order_by("sequence")
                )
                if action == "tax_recognize":
                    assert not (
                        len(liabilities_now) != 1
                        or Decimal(liabilities_now[0].cash_delta_text) != Decimal("0")
                        or account.current_cash != after_payment_cash
                    ), "tax recognition changed cash or has an invalid history"
                    continue

                assert (
                    withholding_amount is not None and len(liabilities_now) == 2
                ), "tax collection has no exact preceding assessment and recognition"
                collected = liabilities_now[-1]
                assert not (
                    Decimal(collected.cash_delta_text) != -withholding_amount
                    or Decimal(collected.collected_delta_text) != withholding_amount
                    or Decimal(collected.outstanding_amount_text) != Decimal("0")
                    or account.current_cash != after_payment_cash - withholding_amount
                ), "tax collection did not exactly reconcile cash and liability"

            rows = list(
                CorporateActionPostingModel.objects.filter(
                    account_id=world.account_id,
                    source_event_id=entitlement.source_event_id,
                ).order_by("account_revision")
            )
            assessments = CorporateActionTaxAssessmentHeaderModel.objects.filter(
                account_id=world.account_id,
                source_event_id=entitlement.source_event_id,
                settlement_date=world.settlement_date,
            )
            liabilities = list(
                CorporateActionTaxLiabilityOperationModel.objects.filter(
                    account_id=world.account_id
                ).order_by("sequence")
            )
            account.refresh_from_db()
            assert not (
                [row.stage for row in rows] != ["cash_entitlement", "cash_payment"]
                or assessments.count() != 1
                or [row.sequence for row in liabilities] != [1, 2]
                or withholding_amount is None
                or Decimal(liabilities[-1].outstanding_amount_text) != Decimal("0")
                or account.current_cash
                != starting_cash + entitlement.cash_amount - withholding_amount
            ), "the complete cash/tax journey did not preserve its ledger order"
            _read_receipts(
                page,
                world,
                (
                    "登记模拟现金权益",
                    "模拟分红到账",
                    "模拟税务评估",
                    "模拟税务财务回执",
                ),
            )
            assert b"%ASH05 synthetic fixture" in world.capture.pdf_body
            _save_screenshot_if_configured(page, "cash-tax-workflow.png")
            _assert_browser_clean(state)


def test_nonstaff_owner_completes_share_entitlement_delivery_and_release_from_the_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live_server: Any,
) -> None:
    """Complete the three separate synthetic share stages using share-only grants."""
    if connection.vendor != "postgresql":
        pytest.skip("the migrated ordinary-owner browser journey runs only on assigned PostgreSQL")
    with isolated_task_channels(), override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="share",
        )
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        starting_cash = account.current_cash
        starting_quantity = position.quantity
        starting_available = position.available_quantity
        if not (world.record_date < world.share_delivery_date <= world.share_sellable_date):
            raise AssertionError(
                "the synthetic share dates do not follow the confirmed source order"
            )
        with _ordinary_owner_browser(world, live_server=live_server) as (_context, page, state):
            _refresh_account(page, world, has_financial_history=False)
            _select_consent(page, world, capabilities=("share_distribution",), state=state)
            source_event_id = _load_event_row(page, world)
            for index, action in enumerate(
                ("share_entitlement", "share_delivery", "share_sellable_release")
            ):
                if index:
                    _refresh_account(page, world, has_financial_history=True)
                    _select_consent(page, world, capabilities=("share_distribution",), state=state)
                before = _business_effect_counts(world.account_id)
                token = _prepare_workflow_intent(page, world, action=action, state=state)
                _confirm_continuation(
                    page,
                    panel_key="corporate-action-workflow-result",
                    target_action=_CONFIRM_ACTION,
                    token=token,
                    state=state,
                )
                _assert_effect_delta(
                    before, _business_effect_counts(world.account_id), _EXPECTED_EFFECTS[action]
                )
                if index == 0:
                    after_commit = _business_effect_counts(world.account_id)
                    _replay_same_tui_confirmation(
                        _context,
                        page,
                        base_url=live_server.url,
                        csrf_token=world.owner.csrf_token,
                        world=world,
                        token=token,
                        state=state,
                    )
                    if _business_effect_counts(world.account_id) != after_commit:
                        raise AssertionError("share entitlement replay changed financial effects")

            _refresh_account(page, world, has_financial_history=True)
            rows = list(
                CorporateActionPostingModel.objects.filter(
                    account_id=world.account_id,
                    source_event_id=source_event_id,
                ).order_by("account_revision")
            )
            account.refresh_from_db()
            position.refresh_from_db()
            if (
                [row.stage for row in rows]
                != ["share_entitlement", "share_delivery", "share_sellable_release"]
                or [row.entry_kind for row in rows] != ["posting", "posting", "posting"]
                or rows[0].eligible_quantity != Decimal("100.000000")
                or rows[0].share_amount != Decimal("10.000000")
                or account.current_cash != starting_cash
                or position.quantity != starting_quantity + Decimal("10.000000")
                or position.available_quantity != starting_available + Decimal("10.000000")
                or CorporateActionTaxAssessmentHeaderModel.objects.filter(
                    account_id=world.account_id, source_event_id=source_event_id
                ).exists()
                or CorporateActionTaxLiabilityOperationModel.objects.filter(
                    account_id=world.account_id
                ).exists()
            ):
                raise AssertionError("the share journey did not preserve its three-stage ledger")
            _read_receipts(
                page,
                world,
                ("登记送转权益", "送转记入模拟持仓", "释放模拟可用股份"),
            )
            if b"%ASH05 synthetic fixture" not in world.capture.pdf_body:
                raise AssertionError("the fixture lost its explicit synthetic-source label")
            _save_screenshot_if_configured(page, "share-workflow.png")
            _assert_browser_clean(state)


def test_nonstaff_owner_records_rights_no_effect_from_the_tui(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live_server: Any,
) -> None:
    """Record only an explicitly authorized rights non-participation with zero cash/share deltas."""
    if connection.vendor != "postgresql":
        pytest.skip("the migrated ordinary-owner browser journey runs only on assigned PostgreSQL")
    with isolated_task_channels(), override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="rights",
        )
        with _ordinary_owner_browser(world, live_server=live_server) as (_context, page, state):
            _refresh_account(page, world, has_financial_history=False)
            _select_consent(page, world, capabilities=("rights_not_exercised",), state=state)
            source_event_id = _load_event_row(page, world)
            account = SimulatedAccountModel.objects.get(pk=world.account_id)
            position = PositionModel.objects.get(
                account_id=world.account_id, asset_code=world.asset_code
            )
            before_cash = account.current_cash
            before_quantity = position.quantity
            before_available = position.available_quantity
            before = _business_effect_counts(world.account_id)
            token = _prepare_workflow_intent(
                page, world, action="rights_not_exercised", state=state
            )
            _confirm_continuation(
                page,
                panel_key="corporate-action-workflow-result",
                target_action=_CONFIRM_ACTION,
                token=token,
                state=state,
            )
            _assert_effect_delta(
                before,
                _business_effect_counts(world.account_id),
                _EXPECTED_EFFECTS["rights_not_exercised"],
            )
            row = CorporateActionPostingModel.objects.get(
                account_id=world.account_id,
                source_event_id=source_event_id,
                stage="rights_not_exercised",
            )
            account.refresh_from_db()
            position.refresh_from_db()
            if (
                row.action_kind != "rights_issue"
                or row.entry_kind != "no_effect"
                or row.rights_election != "not_exercised"
                or row.cash_delta != Decimal("0.00")
                or row.share_delta != Decimal("0.000000")
                or row.cash_receivable_delta != Decimal("0.00")
                or row.share_receivable_delta != Decimal("0.000000")
                or account.current_cash != before_cash
                or position.quantity != before_quantity
                or position.available_quantity != before_available
                or CorporateActionTaxAssessmentHeaderModel.objects.filter(
                    account_id=world.account_id
                ).exists()
                or CorporateActionTaxLiabilityOperationModel.objects.filter(
                    account_id=world.account_id
                ).exists()
            ):
                raise AssertionError("rights non-participation changed financial balances or tax")
            _read_receipts(page, world, ("模拟未参与配股",))
            if b"%ASH05 synthetic fixture" not in world.capture.pdf_body:
                raise AssertionError("the fixture lost its explicit synthetic-source label")
            _save_screenshot_if_configured(page, "rights-no-effect-workflow.png")
            _assert_browser_clean(state)


def test_prepared_owner_intent_is_blocked_after_tui_withdrawal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live_server: Any,
) -> None:
    """A second ordinary-user tab can withdraw consent before a prepared operation is confirmed."""
    if connection.vendor != "postgresql":
        pytest.skip("the migrated ordinary-owner browser journey runs only on assigned PostgreSQL")
    with isolated_task_channels(), override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        with _ordinary_owner_browser(world, live_server=live_server) as (context, page, state):
            _refresh_account(page, world, has_financial_history=False)
            _select_consent(page, world, capabilities=("cash_dividend",), state=state)
            _load_event_row(page, world)
            token = _prepare_workflow_intent(page, world, action="cash_entitlement", state=state)
            pending_baseline = _business_effect_counts(world.account_id)

            withdrawal_page = context.new_page()
            withdrawal_page.on(
                "console", lambda message: state["console_pending"].append(message.text)
            )
            withdrawal_page.on("pageerror", lambda _error: state.__setitem__("page_errors", 1))
            withdrawal_page.on(
                "response",
                lambda response: (
                    state["action_responses"].append(
                        (urlsplit(response.url).path, int(response.status))
                    )
                    if urlsplit(response.url).path.startswith("/api/tui/actions/")
                    else None
                ),
            )
            withdrawal_page.set_default_timeout(180_000)
            withdrawal_page.set_default_navigation_timeout(180_000)
            _open_owner_workflow(withdrawal_page, base_url=live_server.url)
            withdrawal_token = _prepare_withdrawal(withdrawal_page, world, state=state)
            _confirm_continuation(
                withdrawal_page,
                panel_key="corporate-action-withdrawal-result",
                target_action=_CONSENT_WITHDRAW_ACTION,
                token=withdrawal_token,
                state=state,
            )
            after_withdrawal = _business_effect_counts(world.account_id)
            if after_withdrawal[0:3] != pending_baseline[0:3]:
                raise AssertionError("withdrawing consent changed a financial ledger")

            _confirm_continuation(
                page,
                panel_key="corporate-action-workflow-result",
                target_action=_CONFIRM_ACTION,
                token=token,
                state=state,
                expect_revoked=True,
            )
            if _business_effect_counts(world.account_id) != after_withdrawal:
                raise AssertionError(
                    "the withdrawn prepared intent changed financial/Audit/Outbox effects"
                )
            if CorporateActionPostingModel.objects.filter(account_id=world.account_id).exists():
                raise AssertionError(
                    "the withdrawn prepared intent wrote a corporate-action ledger row"
                )
            _save_screenshot_if_configured(withdrawal_page, "withdrawn-intent-blocked.png")
            _assert_browser_clean(state)


def _prepare_withdrawal(
    page: Any, world: OwnerWorkflowNativeWorld, *, state: dict[str, Any]
) -> str:
    """Prepare the exact current consent withdrawal through its visible TUI panel."""
    payload = _run_dashboard_action(
        page,
        panel_key="corporate-action-withdrawal-result",
        action_key=_CONSENT_WITHDRAW_PREPARE_ACTION,
        fields={"account_id": world.account_id},
    )
    _expect_action_success(payload)
    token = _continuation_token(
        payload,
        expected_action=_CONSENT_WITHDRAW_ACTION,
        token_field="withdrawal_token",
    )
    _assert_secret_not_exposed(page, token, state=state)
    return token
