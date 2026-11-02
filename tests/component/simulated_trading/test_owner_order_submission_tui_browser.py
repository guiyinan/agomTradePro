"""Exercise the real owner order flow through the authenticated TUI."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from django.apps import apps
from django.conf import settings
from django.db.backends.utils import CursorWrapper
from django.utils import timezone as django_timezone
from playwright.sync_api import Route, expect, sync_playwright

from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from shared.infrastructure.async_runtime import run_sync_compatible
from tests.component.equity.test_research_snapshot_tui_browser import (
    loopback_only_python_network as loopback_only_python_network,
)
from tests.component.equity.test_research_snapshot_tui_browser import (
    subprocess_policy as subprocess_policy,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    AS_OF,
    ASSET_CODE,
    ASSET_NAME,
    _owner_session_client,
    _persist_sell_position,
    _QualifiedCallerContext,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _clear_runtime_profile_history as _clear_runtime_profile_history,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    _freeze_auto_fixture_knowledge_clocks as _freeze_auto_fixture_knowledge_clocks,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    persisted_source_snapshot as persisted_source_snapshot,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    qualified_caller_context as qualified_caller_context,
)
from tests.component.simulated_trading.test_owner_order_submission_api import (
    public_order_context as public_order_context,
)

SCREEN = "simulated-trading.order-entry"
PREVIEW_ACTION_PATH = "/api/tui/actions/simulated-trading.order-preview/run/"
CONFIRM_ACTION_PATH = "/api/tui/actions/simulated-trading.order-confirm/run/"
READBACK_ACTION_PATH = "/api/tui/actions/simulated-trading.order-by-key/run/"

pytestmark = pytest.mark.django_db(transaction=True)


def _business_state(
    account: SimulatedAccountModel,
    position: PositionModel,
) -> dict[str, str | int]:
    """Read database state on a synchronous thread, including inside Playwright."""

    account_id = account.pk
    position_id = position.pk

    def read_state() -> dict[str, str | int]:
        current_account = SimulatedAccountModel.objects.get(pk=account_id)
        current_position = PositionModel.objects.get(pk=position_id)
        active_sell_holds = list(
            SimulatedOrderReservationModel.objects.filter(
                account_id=account_id,
                side="sell",
                status=SimulatedOrderReservationModel.STATUS_ACTIVE,
            )
        )
        held_quantity = sum((hold.shares_reserved for hold in active_sell_holds), Decimal("0"))
        return {
            "cash": str(current_account.current_cash),
            "market_value": str(current_account.current_market_value),
            "total_value": str(current_account.total_value),
            "position_quantity": str(current_position.quantity),
            "available_quantity": str(current_position.available_quantity),
            "active_sell_hold_quantity": str(held_quantity),
            "free_sell_quantity": str(current_position.available_quantity - held_quantity),
            "reservation_count": SimulatedOrderReservationModel.objects.filter(
                account_id=account_id
            ).count(),
            "trade_count": SimulatedTradeModel.objects.filter(account_id=account_id).count(),
        }

    return run_sync_compatible(read_state)


def _aware_datetime(value: object) -> datetime:
    """Parse one TUI ISO timestamp and require its UTC offset."""

    assert type(value) is str and value
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def _is_simulated_table_write(sql: object, table_names: frozenset[str]) -> bool:
    """Identify DML against simulated-trading or the held-position table."""

    statement = str(sql).lstrip().casefold()
    verb = statement.split(None, 1)[0] if statement else ""
    if verb not in {"insert", "update", "delete", "replace"}:
        return False
    return any(table in statement for table in table_names)


def _write_response_artifact(
    evidence_dir: Path,
    filename: str,
    status_code: int,
    body: object,
) -> None:
    """Retain one complete local TUI HTTP response for failed-journey diagnosis."""

    artifact = {"status_code": status_code, "body": body}
    (evidence_dir / filename).write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "viewport",
    [(1440, 1000), (390, 844)],
    ids=["desktop", "narrow"],
)
def test_ordinary_owner_previews_confirms_and_reads_original_order_in_tui(
    public_order_context: tuple[_QualifiedCallerContext, list[str]],
    live_server: Any,
    subprocess_policy: None,
    loopback_only_python_network: list[str],
    viewport: tuple[int, int],
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview without business writes, confirm once, then recover by-key in TUI."""

    fixture_context, capture_calls = public_order_context
    # The qualified fixture pins this shared module used by terminal execution;
    # repatching it here would also alter the fixture's source-knowledge clocks.
    assert django_timezone.now() == AS_OF
    account = fixture_context.account
    position = _persist_sell_position(account)
    account.current_market_value = position.market_value
    account.total_value = account.current_cash + position.market_value
    account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )
    initial_state = _business_state(account, position)
    assert initial_state["reservation_count"] == 0
    assert initial_state["trade_count"] == 0

    client, csrf_token = _owner_session_client(fixture_context.owner_id)
    session_cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
    csrf_cookie = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert csrf_cookie == csrf_token
    evidence_dir = tmp_path / "browser" / request.node.name
    evidence_dir.mkdir(parents=True, exist_ok=True)

    simulated_tables = {
        model._meta.db_table.casefold()
        for model in apps.get_app_config("simulated_trading").get_models()
    }
    simulated_tables.add(PositionModel._meta.db_table.casefold())
    simulated_table_names = frozenset(simulated_tables)
    capture_simulated_dml = threading.Event()
    preview_simulated_dml: list[str] = []
    readback_simulated_dml: list[str] = []
    active_dml_log = preview_simulated_dml
    original_execute = CursorWrapper.execute
    original_executemany = CursorWrapper.executemany

    def observe_execute(
        cursor: CursorWrapper,
        sql: Any,
        params: Any = None,
    ) -> Any:
        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_execute(cursor, sql, params)

    def observe_executemany(
        cursor: CursorWrapper,
        sql: Any,
        param_list: Any,
    ) -> Any:
        if capture_simulated_dml.is_set() and _is_simulated_table_write(sql, simulated_table_names):
            active_dml_log.append(str(sql).lstrip().split(None, 1)[0].upper())
        return original_executemany(cursor, sql, param_list)

    monkeypatch.setattr(CursorWrapper, "execute", observe_execute)
    monkeypatch.setattr(CursorWrapper, "executemany", observe_executemany)

    browser_requests: list[dict[str, str]] = []
    preview_request_parameters: list[dict[str, object]] = []
    nonlocal_browser_attempts: list[str] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    confirmation_upstream: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser_context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]}
        )
        browser_context.clock.install(time=AS_OF)
        browser_context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie,
                    "url": live_server.url,
                },
                {
                    "name": settings.CSRF_COOKIE_NAME,
                    "value": csrf_cookie,
                    "url": live_server.url,
                },
            ]
        )

        def local_only(route: Route) -> None:
            """Keep the browser on the local server origin."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.scheme not in {"http", "https"} or target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return
            route.continue_()

        def simulate_lost_confirm_response(route: Route) -> None:
            """Commit the real confirmation, then lose only its browser response."""

            target = urlsplit(route.request.url)
            expected = urlsplit(live_server.url)
            if target.netloc != expected.netloc:
                nonlocal_browser_attempts.append(route.request.url)
                route.abort("blockedbyclient")
                return

            request_body = route.request.post_data_json
            confirmed = isinstance(request_body, dict) and request_body.get("confirmed") is True
            if not confirmed:
                route.continue_()
                return

            upstream = route.fetch()
            upstream_payload = upstream.json()
            upstream_response = (
                upstream_payload.get("response") if isinstance(upstream_payload, dict) else None
            )
            _write_response_artifact(
                evidence_dir,
                "confirm-upstream-response.json",
                upstream.status,
                upstream_payload,
            )
            confirmation_upstream.append(
                {
                    "http_status": upstream.status,
                    "business_status": (
                        upstream_response.get("status_code")
                        if isinstance(upstream_response, dict)
                        else None
                    ),
                    "outcome": (
                        upstream_payload.get("outcome")
                        if isinstance(upstream_payload, dict)
                        else None
                    ),
                }
            )
            route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps({"detail": "test-only browser response loss after local commit"}),
            )

        browser_context.route("**/*", local_only)
        browser_context.route(
            f"{live_server.url}{CONFIRM_ACTION_PATH}",
            simulate_lost_confirm_response,
        )
        page = browser_context.new_page()

        def record_action_request(browser_request: Any) -> None:
            path = urlsplit(browser_request.url).path
            if path in {
                PREVIEW_ACTION_PATH,
                CONFIRM_ACTION_PATH,
                READBACK_ACTION_PATH,
            }:
                browser_requests.append(
                    {
                        "path": path,
                        "method": browser_request.method,
                        "idempotency_key": browser_request.headers.get("idempotency-key", ""),
                    }
                )
                if path == PREVIEW_ACTION_PATH:
                    request_body = browser_request.post_data_json
                    request_params = (
                        request_body.get("params") if isinstance(request_body, dict) else None
                    )
                    if isinstance(request_params, dict):
                        preview_request_parameters.append(
                            {
                                field: request_params.get(field)
                                for field in ("quantity", "limit_price", "fee_budget")
                            }
                        )

        page.on("request", record_action_request)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda browser_request: request_failures.append(
                f"{browser_request.method} {browser_request.url}: {browser_request.failure}"
            ),
        )
        try:
            page.goto(
                f"{live_server.url}/tui/?screen={SCREEN}",
                wait_until="networkidle",
            )
            panel = page.locator('[data-main-panel] [data-dashboard-panel="order-entry-intent"]')
            form = panel.locator("form.tui-action-form")
            expect(form).to_be_visible()
            assert form.count() == 1
            account_select = form.locator('[name="account_id"]')
            owned_account_option = account_select.locator(f'option[value="{account.pk}"]')
            expect(owned_account_option).to_have_count(1)
            account_select.select_option(value=str(account.pk))
            expect(account_select).to_have_value(str(account.pk))
            form.locator('[name="asset_code"]').fill(ASSET_CODE)
            form.locator('[name="asset_name"]').fill(ASSET_NAME)
            form.locator('[name="side"]').select_option("sell")
            form.locator('[name="quantity"]').fill("100")
            form.locator('[name="limit_price"]').fill("10.00")

            capture_simulated_dml.set()
            try:
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == PREVIEW_ACTION_PATH
                ) as preview_response:
                    form.locator(".tui-action-submit").click()
            finally:
                capture_simulated_dml.clear()

            preview_http = preview_response.value
            preview = preview_http.json()
            actual_continuation = preview.get("continuation")
            actual_continuation_input = (
                actual_continuation.get("input") if isinstance(actual_continuation, dict) else None
            )
            actual_preview_token = (
                actual_continuation_input.get("preview_token")
                if isinstance(actual_continuation_input, dict)
                else None
            )
            sanitized_preview_request = (
                preview_request_parameters[0] if len(preview_request_parameters) == 1 else None
            )
            (evidence_dir / "preview-request-body.json").write_text(
                json.dumps(
                    {"params": sanitized_preview_request},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            preview_artifact = dict(preview)
            artifact_continuation = preview_artifact.get("continuation")
            if isinstance(artifact_continuation, dict):
                safe_continuation = {
                    key: artifact_continuation[key]
                    for key in ("action_key", "expires_at")
                    if key in artifact_continuation
                }
                continuation_input = artifact_continuation.get("input")
                if isinstance(continuation_input, dict):
                    safe_continuation["input"] = {
                        key: continuation_input[key]
                        for key in ("account_id", "order_key")
                        if key in continuation_input
                    }
                preview_artifact["continuation"] = safe_continuation
            serialized_preview_artifact = json.dumps(preview_artifact, ensure_ascii=False)
            assert type(actual_preview_token) is str and actual_preview_token
            assert actual_preview_token not in serialized_preview_artifact
            _write_response_artifact(
                evidence_dir,
                "preview-response.json",
                preview_http.status,
                preview_artifact,
            )
            assert sanitized_preview_request == {
                "quantity": "100",
                "limit_price": "10.00",
                "fee_budget": None,
            }
            assert preview_http.status == 200
            assert preview.get("outcome") == "success"
            assert preview.get("response", {}).get("status_code") == 200
            assert preview.get("view_model", {}).get("outcome") == "success"
            assert preview_simulated_dml == []
            assert _business_state(account, position) == initial_state
            assert capture_calls == [ASSET_CODE]

            continuation = preview.get("continuation")
            assert isinstance(continuation, dict)
            assert continuation.get("action_key") == "simulated-trading.order-confirm"
            continuation_input = continuation.get("input")
            assert isinstance(continuation_input, dict)
            order_key = continuation_input.get("order_key")
            assert type(order_key) is str and order_key
            assert continuation_input.get("preview_token") == actual_preview_token
            view_model = preview.get("view_model")
            assert isinstance(view_model, dict)
            summary = view_model.get("business_summary")
            assert type(summary) is str and summary
            field_values = {
                field["key"]: field.get("value")
                for field in view_model.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            assert field_values.get("asset_code") == ASSET_CODE
            assert field_values.get("side") == "卖出"
            assert Decimal(str(field_values.get("quantity"))) == Decimal("100")
            assert Decimal(str(field_values.get("limit_price"))) == Decimal("10.00")
            assert field_values.get("fee_estimate") is not None
            observed_at = _aware_datetime(field_values.get("market_observed_at"))
            available_at = _aware_datetime(field_values.get("market_available_at"))
            confirmation_expires_at = _aware_datetime(field_values.get("continuation_expires_at"))
            assert observed_at.date().isoformat() == AS_OF.date().isoformat()
            assert observed_at < available_at < AS_OF
            assert confirmation_expires_at > AS_OF
            for visible_fact in (
                ASSET_CODE,
                "卖出",
                "100",
                "10.00",
                "预估费用",
                str(field_values["market_observed_at"]),
                str(field_values["continuation_expires_at"]),
                "不会提交券商",
            ):
                assert visible_fact in summary
            main_panel = page.locator("[data-main-panel]")
            expect(main_panel).to_contain_text("不会提交券商")
            expect(main_panel).to_contain_text(ASSET_CODE)
            assert main_panel.evaluate("element => element.scrollWidth") <= viewport[0] + 1

            preview_key_headers = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == PREVIEW_ACTION_PATH
            ]
            assert len(preview_key_headers) == 1 and preview_key_headers[0]

            continue_button = page.get_by_role(
                "button",
                name="继续：确认模拟订单预留",
                exact=True,
            )
            expect(continue_button).to_be_visible()
            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as preflight_response:
                continue_button.click()
            preflight_http = preflight_response.value
            preflight = preflight_http.json()
            _write_response_artifact(
                evidence_dir, "confirm-preflight-response.json", preflight_http.status, preflight
            )
            assert preflight_http.status == 200
            assert preflight.get("confirmation_required") is True
            assert preflight.get("response", {}).get("status_code") == 409
            expect(page.locator("[data-tui-modal]")).to_be_visible()
            confirm_button = page.locator("[data-tui-modal] [data-confirm-action]")
            expect(confirm_button).to_be_visible()
            assert _business_state(account, position) == initial_state
            assert capture_calls == [ASSET_CODE]

            with page.expect_response(
                lambda response: urlsplit(response.url).path == CONFIRM_ACTION_PATH
            ) as lost_confirm_response:
                confirm_button.click()
            lost_confirm_http = lost_confirm_response.value
            lost_confirm_body = lost_confirm_http.json()
            _write_response_artifact(
                evidence_dir,
                "confirm-browser-response.json",
                lost_confirm_http.status,
                lost_confirm_body,
            )
            assert lost_confirm_http.status == 502
            assert confirmation_upstream == [
                {"http_status": 200, "business_status": 200, "outcome": "success"}
            ]
            confirmation_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == CONFIRM_ACTION_PATH
            ]
            assert len(confirmation_keys) == 2
            assert confirmation_keys == [preview_key_headers[0], preview_key_headers[0]]

            reservations = run_sync_compatible(
                lambda: list(SimulatedOrderReservationModel.objects.filter(account_id=account.pk))
            )
            assert len(reservations) == 1
            reservation = reservations[0]
            assert reservation.idempotency_key == order_key
            assert reservation.owner_user_id == fixture_context.owner_id
            assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
            assert reservation.side == "sell"
            assert reservation.quantity == Decimal("100")
            assert reservation.limit_price == Decimal("10.00")
            assert reservation.shares_reserved == Decimal("100")
            assert reservation.filled_quantity == Decimal("0")
            assert "submission_market" in reservation.plan_snapshot
            after_confirm = _business_state(account, position)
            assert after_confirm["cash"] == initial_state["cash"]
            assert after_confirm["position_quantity"] == initial_state["position_quantity"]
            assert after_confirm["available_quantity"] == initial_state["available_quantity"]
            assert Decimal(str(after_confirm["active_sell_hold_quantity"])) == Decimal("100")
            assert Decimal(str(initial_state["free_sell_quantity"])) - Decimal(
                str(after_confirm["free_sell_quantity"])
            ) == Decimal("100")
            assert after_confirm["reservation_count"] == 1
            assert after_confirm["trade_count"] == 0
            expect(page.locator("[data-main-panel]")).to_contain_text("原请求结果待确认")
            page.screenshot(path=str(evidence_dir / "unknown-confirm.png"))

            readback_button = page.locator("[data-main-panel] [data-continuation-readback]")
            expect(readback_button).to_be_visible()
            active_dml_log = readback_simulated_dml
            capture_simulated_dml.set()
            try:
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == READBACK_ACTION_PATH
                ) as readback_response:
                    readback_button.click()
            finally:
                capture_simulated_dml.clear()

            readback_http = readback_response.value
            readback = readback_http.json()
            _write_response_artifact(
                evidence_dir, "readback-response.json", readback_http.status, readback
            )
            assert readback_http.status == 200
            assert readback.get("outcome") == "success"
            assert readback.get("response", {}).get("status_code") == 200
            readback_action = readback.get("action")
            assert isinstance(readback_action, dict)
            assert readback_action.get("key") == "simulated-trading.order-by-key"
            assert readback_action.get("method") == "GET"
            readback_keys = [
                item["idempotency_key"]
                for item in browser_requests
                if item["path"] == READBACK_ACTION_PATH
            ]
            assert readback_keys == [preview_key_headers[0]]
            assert readback_simulated_dml == []
            assert capture_calls == [ASSET_CODE]
            assert _business_state(account, position) == after_confirm

            readback_view = readback.get("view_model")
            assert isinstance(readback_view, dict)
            assert readback_view.get("outcome") == "success"
            readback_summary = readback_view.get("business_summary")
            assert type(readback_summary) is str
            assert "已找到同一原订单" in readback_summary
            assert "未重新读取行情或创建新单" in readback_summary
            readback_fields = {
                field["key"]: field.get("value")
                for field in readback_view.get("fields", [])
                if isinstance(field, dict) and type(field.get("key")) is str
            }
            assert int(readback_fields["order_id"]) == reservation.pk
            assert readback_fields["side"] == "卖出"
            assert Decimal(str(readback_fields["quantity"])) == Decimal("100")
            assert Decimal(str(readback_fields["filled_quantity"])) == Decimal("0")
            expect(page.locator("[data-main-panel]")).to_contain_text("已找到同一原订单")
            expect(page.locator("[data-main-panel]")).to_contain_text("累计成交数量 0")
            assert (
                page.locator("[data-main-panel]").evaluate("element => element.scrollWidth")
                <= viewport[0] + 1
            )
            page.screenshot(path=str(evidence_dir / "readback.png"))

            assert page_errors == []
            assert request_failures == []
            assert nonlocal_browser_attempts == []
            assert loopback_only_python_network == []
            safe_evidence = {
                "case": request.node.name,
                "screen": SCREEN,
                "viewport": {"width": viewport[0], "height": viewport[1]},
                "as_of": AS_OF.isoformat(),
                "simulation_scope": "explicit local fixture; no brokerage submission",
                "preview_summary": summary,
                "preview_request_params": sanitized_preview_request,
                "preview_simulated_table_dml": preview_simulated_dml,
                "confirm_upstream": confirmation_upstream,
                "readback": {
                    "action_key": readback_action["key"],
                    "method": readback_action["method"],
                    "order_id": reservation.pk,
                    "status": readback_view.get("status"),
                },
                "final_business_state": after_confirm,
                "capture_calls": capture_calls,
                "page_errors": page_errors,
                "request_failures": request_failures,
                "nonlocal_browser_attempts": nonlocal_browser_attempts,
                "nonlocal_python_socket_attempts": loopback_only_python_network,
            }
            (evidence_dir / "journey.json").write_text(
                json.dumps(safe_evidence, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        finally:
            try:
                if not page.is_closed():
                    page.screenshot(
                        path=str(evidence_dir / "final-diagnostic.png"),
                        full_page=True,
                    )
            finally:
                browser_context.close()
                browser.close()
