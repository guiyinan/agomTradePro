"""Ordinary-owner browser checks for persisted local match history."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client
from playwright.sync_api import Page, Route, expect, sync_playwright

from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.account.test_authentication import _create_profile
from tests.component.simulated_trading.test_order_decision_history_api import (
    _OrderDecisionHistoryCase,
)
from tests.component.simulated_trading.test_order_decision_history_api import ledger as ledger
from tests.component.simulated_trading.test_order_decision_history_api import (
    local_daily_match_schema as local_daily_match_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    order_decision_history_case as order_decision_history_case,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.component.simulated_trading.test_order_decision_history_api import (
    reservation_harness as reservation_harness,
)
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
    _form,
    _response,
)
from tests.integration.simulated_trading.test_order_history_browser import _fields
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy

pytestmark = pytest.mark.django_db(transaction=True)

_ORDERS = "simulated-trading.orders"
_DECISIONS = "simulated-trading.order-decisions"
_DECISION_SECTION = "本页原撮合决定"


@dataclass(frozen=True, slots=True)
class _DecisionBrowserSession:
    """The live browser page and isolated evidence directory for one viewport."""

    page: Page
    evidence_directory: Path


@pytest.fixture
def decision_scope_account(
    order_decision_history_case: _OrderDecisionHistoryCase,
) -> SimulatedAccountModel:
    """Create a same-owner account without the tested order for scope switching."""

    harness = order_decision_history_case.harness
    return SimulatedAccountModel.objects.create(
        user=order_decision_history_case.owner,
        account_name="Decision history scope switch",
        account_type="simulated",
        initial_capital=harness.account.initial_capital,
        current_cash=harness.account.initial_capital,
        total_value=harness.account.initial_capital,
    )


@pytest.fixture
def decision_browser(
    live_server: Any,
    order_decision_history_case: _OrderDecisionHistoryCase,
    decision_scope_account: SimulatedAccountModel,
    local_daily_match_schema: None,
    persisted_receipt_schema: None,
    request: pytest.FixtureRequest,
) -> Iterator[_DecisionBrowserSession]:
    """Use the real owner's session and keep all browser traffic on loopback."""

    del decision_scope_account, local_daily_match_schema, persisted_receipt_schema
    case = order_decision_history_case
    _create_profile(case.owner)
    client = Client(enforce_csrf_checks=True)
    client.force_login(case.owner)
    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    errors: list[str] = []
    traffic: list[dict[str, str]] = []
    viewport = request.param
    evidence_directory = Path(settings.BASE_DIR) / (
        "artifacts/a-share-usability/ash03-order-recovery-2026-10-29/"
        f"order-decisions/browser-{viewport['width']}-{uuid4().hex[:8]}"
    )
    evidence_directory.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport=viewport)
        context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                    "url": live_server.url,
                }
            ]
        )

        def local_only(route: Route) -> None:
            """Reject remote requests instead of silently using a real source."""

            if urlsplit(route.request.url).netloc != urlsplit(live_server.url).netloc:
                errors.append(f"Nonlocal request: {route.request.url}")
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: traffic.append({"method": req.method, "url": req.url}))
        try:
            page.goto(f"{live_server.url}/tui/?screen=execution.accounts", wait_until="networkidle")
            expect(page.locator("[data-main-panel]")).to_be_visible()
            page.locator('[data-experience-mode="professional"]').click()
            page.keyboard.press("F9")
            expect(page.locator("[data-actions-panel]")).to_be_visible()
            yield _DecisionBrowserSession(page=page, evidence_directory=evidence_directory)
            assert errors == []
        finally:
            page.screenshot(path=str(evidence_directory / "final-viewport.png"))
            (evidence_directory / "traffic.json").write_text(
                json.dumps({"requests": traffic, "page_errors": errors}, indent=2),
                encoding="utf-8",
            )
            context.close()
            browser.close()
            if changed:
                asyncio.set_event_loop_policy(original_policy)


def _financial_state(case: _OrderDecisionHistoryCase) -> object:
    """Snapshot account, order, receipt, decision, position, and trade rows."""

    def read() -> object:
        account_id = case.harness.account.pk
        return (
            tuple(SimulatedAccountModel._base_manager.filter(pk=account_id).values()),
            tuple(
                PositionModel._base_manager.filter(account_id=account_id).order_by("pk").values()
            ),
            tuple(
                SimulatedTradeModel._base_manager.filter(account_id=account_id)
                .order_by("pk")
                .values()
            ),
            tuple(
                SimulatedOrderReservationModel._base_manager.filter(account_id=account_id)
                .order_by("pk")
                .values()
            ),
            tuple(
                SimulatedOrderFillReceiptModel._base_manager.filter(
                    reservation__account_id=account_id
                )
                .order_by("pk")
                .values()
            ),
            tuple(
                LocalDailyMatchModel._base_manager.filter(account_id=account_id)
                .order_by("pk")
                .values()
            ),
        )

    return _db_call(read)


def _row_fields(response: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
    """Return fields from one actual projected decision row."""

    row = response["view_model"]["sections"][0]["rows"][index]
    return _fields(row["fields"])


@pytest.mark.parametrize(
    "decision_browser",
    [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
    indirect=True,
)
def test_owner_opens_persisted_decisions_pages_states_and_clears_foreign_scope(
    decision_browser: _DecisionBrowserSession,
    order_decision_history_case: _OrderDecisionHistoryCase,
    decision_scope_account: SimulatedAccountModel,
) -> None:
    """Show retained NO_MATCH/MATCHED states without recording or applying anything."""

    page = decision_browser.page
    case = order_decision_history_case
    before = _financial_state(case)

    orders_form = _form(page, _ORDERS)
    orders_form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    orders_form.locator('[name="limit"]').fill("1")
    orders_response = _response(page, _ORDERS, orders_form.locator(".tui-action-submit").click)
    assert orders_response["response"]["status_code"] == 200
    order_row = _fields(orders_response["view_model"]["sections"][0]["rows"][0]["fields"])
    assert order_row["order_id"] == case.order.pk
    assert orders_response["debug"]["raw_available"] is False

    launch = page.get_by_role("button", name=f"核对订单 {case.order.pk} 的撮合决定", exact=True)
    response = _response(page, _DECISIONS, launch.click)
    assert response["response"]["status_code"] == 200
    first_page = _form(page, _DECISIONS)
    first_page.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    first_page.locator('[name="order_id"]').fill(str(case.order.pk))
    first_page.locator('[name="limit"]').fill("1")
    response = _response(page, _DECISIONS, first_page.locator(".tui-action-submit").click)
    assert response["response"]["status_code"] == 200

    no_match_record = _db_call(
        lambda: LocalDailyMatchModel._base_manager.filter(
            account_id=case.harness.account.pk,
            reservation_id=case.order.pk,
            operation_key=case.no_match.command.operation_key,
        )
        .values("pk", "recorded_at")
        .get()
    )

    first_fields = _fields(response["view_model"]["fields"])
    first_row = _row_fields(response)
    assert first_fields["has_more"] == "是"
    assert first_row["decision_id"] == no_match_record["pk"]
    assert first_row["outcome"] == "本次未撮合成交"
    assert first_row["posting_state"] == "本次未撮合成交"
    assert first_row["matched_quantity"] == str(case.no_match.result.matched_quantity)
    assert first_row["matched_price"] is None
    assert first_row["session_date"] == case.no_match.command.session_date.isoformat()
    assert first_row["recorded_at"] == no_match_record["recorded_at"].isoformat()
    assert first_row["occurred_at"] is None
    assert first_row["receipt_id"] is None
    assert first_row["trade_id"] is None
    assert response["debug"]["raw_available"] is False

    section = page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text=_DECISION_SECTION)
    )
    section.locator("summary").click()
    no_match_cells = section.get_by_role("cell", name="本次未撮合成交", exact=True)
    expect(no_match_cells).to_have_count(2)
    expect(no_match_cells.nth(0)).to_be_visible()
    expect(no_match_cells.nth(1)).to_be_visible()
    expect(section.get_by_role("cell", name=str(no_match_record["pk"]), exact=True)).to_be_visible()
    expect(
        section.get_by_role("cell", name=first_row["matched_quantity"], exact=True)
    ).to_be_visible()
    expect(section.get_by_role("cell", name=first_row["recorded_at"], exact=True)).to_be_visible()
    expect(section).to_contain_text(first_row["session_date"])
    page.screenshot(path=str(decision_browser.evidence_directory / "no-match-visible.png"))

    next_page = page.get_by_role("button", name="读取下一批撮合决定", exact=True)
    response = _response(page, _DECISIONS, next_page.click)
    assert response["response"]["status_code"] == 200
    matched_record = _db_call(
        lambda: LocalDailyMatchModel._base_manager.filter(
            account_id=case.harness.account.pk,
            reservation_id=case.order.pk,
            operation_key=case.matched.command.operation_key,
        )
        .values("pk", "recorded_at")
        .get()
    )
    second_fields = _fields(response["view_model"]["fields"])
    second_row = _row_fields(response)
    assert second_fields["membership_cutoff"] == first_fields["membership_cutoff"]
    assert second_fields["has_more"] == "否"
    assert second_row["decision_id"] == matched_record["pk"]
    assert second_row["outcome"] == "已生成模拟成交"
    assert second_row["posting_state"] == "入账尚未确认"
    assert second_row["matched_quantity"] == str(case.matched.result.matched_quantity)
    assert second_row["matched_price"] == str(case.matched.result.matched_price)
    assert second_row["session_date"] == case.matched.command.session_date.isoformat()
    assert case.matched.event is not None
    assert second_row["occurred_at"] == case.matched.event.occurred_at.isoformat()
    assert second_row["recorded_at"] == matched_record["recorded_at"].isoformat()
    assert second_row["receipt_id"] is None
    assert second_row["trade_id"] is None
    assert response["debug"]["raw_available"] is False
    assert case.no_match.command.operation_key not in page.locator("[data-main-panel]").inner_text()
    assert case.matched.command.operation_key not in page.locator("[data-main-panel]").inner_text()
    assert "event_payload_hash" not in page.locator("[data-main-panel]").inner_text()
    assert "request_hash" not in page.locator("[data-main-panel]").inner_text()
    assert "qmt_binding_id" not in page.locator("[data-main-panel]").inner_text()
    assert "source_namespace" not in page.locator("[data-main-panel]").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if page.viewport_size and page.viewport_size["width"] <= 640:
        bounds = page.locator(".tui-main-panel").bounding_box()
        assert bounds and bounds["width"] >= page.viewport_size["width"] * 0.8
    section = page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text=_DECISION_SECTION)
    )
    section.locator("summary").click()
    posting_cell = section.get_by_role("cell", name="入账尚未确认", exact=True)
    posting_cell.scroll_into_view_if_needed()
    expect(posting_cell).to_be_in_viewport()
    expect(
        section.get_by_role("cell", name=second_row["matched_quantity"], exact=True)
    ).to_be_visible()
    expect(
        section.get_by_role("cell", name=second_row["matched_price"], exact=True)
    ).to_be_visible()
    expect(section.get_by_role("cell", name=second_row["occurred_at"], exact=True)).to_be_visible()
    expect(section.get_by_role("cell", name=second_row["recorded_at"], exact=True)).to_be_visible()
    page.screenshot(path=str(decision_browser.evidence_directory / "matched-unconfirmed.png"))
    source_clock = section.get_by_role("cell", name=second_row["recorded_at"], exact=True)
    source_clock.scroll_into_view_if_needed()
    expect(source_clock).to_be_in_viewport()
    page.screenshot(path=str(decision_browser.evidence_directory / "matched-source-clock.png"))

    receipt_link = page.get_by_role("button", name="核对本订单成交回执", exact=True)
    receipts = _response(page, "simulated-trading.order-fills", receipt_link.click)
    assert receipts["response"]["status_code"] == 200
    assert receipts["view_model"]["outcome"] == "success"
    assert receipts["view_model"]["sections"][0]["rows"] == []

    # Reopen the order entry so the new request has an empty cursor scoped to
    # the original account instead of reusing the final-page cursor.
    orders_form = _form(page, _ORDERS)
    orders_form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    orders_form.locator('[name="limit"]').fill("1")
    _response(page, _ORDERS, orders_form.locator(".tui-action-submit").click)
    launch = page.get_by_role("button", name=f"核对订单 {case.order.pk} 的撮合决定", exact=True)
    _response(page, _DECISIONS, launch.click)

    rejected_form = _form(page, _DECISIONS)
    rejected_form.locator('[name="account_id"]').select_option(str(decision_scope_account.pk))
    rejected = _response(page, _DECISIONS, rejected_form.locator(".tui-action-submit").click)
    assert rejected["response"]["status_code"] == 404
    assert rejected["view_model"]["outcome"] == "blocked"
    assert rejected["view_model"]["sections"] == []
    expect(page.locator("[data-main-panel]")).to_contain_text("当前账户或订单范围无法访问")
    expect(page.locator("[data-main-panel]")).not_to_contain_text(first_row["recorded_at"])
    expect(page.locator("[data-main-panel]")).not_to_contain_text(first_row["session_date"])
    expect(page.locator("[data-main-panel]")).not_to_contain_text(second_row["matched_price"])
    expect(page.locator("[data-main-panel]")).not_to_contain_text(second_row["occurred_at"])
    page.screenshot(path=str(decision_browser.evidence_directory / "scope-rejected-cleared.png"))

    assert _financial_state(case) == before
