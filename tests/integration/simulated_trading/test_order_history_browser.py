"""Actual local HTTP/TUI history journeys with synthetic retained fill evidence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from django.conf import settings
from django.test import Client
from playwright.sync_api import Page, Route, expect, sync_playwright

from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.account.test_authentication import _create_profile
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_history_api import (
    _OrderHistoryOwnerReceiptFixture,
)
from tests.component.simulated_trading.test_order_history_api import (
    order_history_owner_with_receipt as order_history_owner_with_receipt,
)
from tests.component.simulated_trading.test_order_history_api import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_history_api import (
    reservation_harness as reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_reservation,
)
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
    _form,
    _response,
)
from tests.playwright.runtime_compatibility import ensure_subprocess_event_loop_policy
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(transaction=True)
_ORDERS = "simulated-trading.orders"
_FILLS = "simulated-trading.order-fills"


@pytest.fixture
def history_page(
    live_server: Any,
    order_history_owner_with_receipt: _OrderHistoryOwnerReceiptFixture,
    request: pytest.FixtureRequest,
) -> Iterator[Page]:
    """Use a genuine ordinary-owner session and permit only loopback HTTP."""

    book = order_history_owner_with_receipt
    _create_profile(book.owner)
    SimulatedAccountModel.objects.create(
        user=book.owner,
        account_name="History scope switch",
        account_type="simulated",
        initial_capital=book.harness.account.initial_capital,
        current_cash=book.harness.account.initial_capital,
        total_value=book.harness.account.initial_capital,
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(book.owner)
    original_policy = asyncio.get_event_loop_policy()
    changed = ensure_subprocess_event_loop_policy()
    errors: list[str] = []
    traffic: list[dict[str, str]] = []
    viewport = request.param
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
            """Reject remote traffic rather than treating a supplier as a fixture."""

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
            yield page
            assert errors == []
        finally:
            evidence = Path(settings.BASE_DIR) / (
                "artifacts/a-share-usability/ash03-order-recovery-2026-10-29/"
                f"order-history/browser-{viewport['width']}-{uuid4().hex[:8]}"
            )
            evidence.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(evidence / "viewport.png"))
            (evidence / "traffic.json").write_text(
                json.dumps({"requests": traffic, "page_errors": errors}, indent=2), encoding="utf-8"
            )
            context.close()
            browser.close()
            if changed:
                asyncio.set_event_loop_policy(original_policy)


def _ledger_state(book: _OrderHistoryOwnerReceiptFixture) -> object:
    """Compare persisted financial rows while allowing normal TUI audit logging."""

    def read() -> object:
        account = SimulatedAccountModel.objects.get(pk=book.harness.account.pk)
        return (
            account.current_cash,
            account.current_market_value,
            account.total_value,
            list(PositionModel.objects.filter(account=account).values()),
            list(SimulatedTradeModel.objects.filter(account=account).values()),
            list(type(book.order).objects.filter(account=account).values()),
            list(type(book.receipt).objects.filter(reservation__account=account).values()),
        )

    return _db_call(read)


def _fields(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Read actual projected detail fields without enabling raw debugging."""

    return {item["key"]: item["value"] for item in items}


@pytest.mark.parametrize(
    "history_page",
    [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
    indirect=True,
)
def test_owner_pages_orders_reads_receipt_and_clears_foreign_scope(
    history_page: Page,
    order_history_owner_with_receipt: _OrderHistoryOwnerReceiptFixture,
) -> None:
    """Navigate actual results, preserving exact receipt facts and zero ledger writes."""

    page = history_page
    book = order_history_owner_with_receipt
    second = _db_call(lambda: _create_reservation(book.harness, key="history-browser-second"))
    before = _ledger_state(book)
    form = _form(page, _ORDERS)
    form.locator('[name="account_id"]').select_option(str(book.harness.account.pk))
    form.locator('[name="limit"]').fill("1")
    response = _response(page, _ORDERS, form.locator(".tui-action-submit").click)
    assert response["response"]["status_code"] == 200
    first_cutoff = _fields(response["view_model"]["fields"])["membership_cutoff"]
    assert (
        _fields(response["view_model"]["sections"][0]["rows"][0]["fields"])["order_id"]
        == book.order.pk
    )
    assert response["debug"]["raw_available"] is False

    response = _response(
        page, _ORDERS, page.get_by_role("button", name="读取下一批订单", exact=True).click
    )
    assert _fields(response["view_model"]["fields"])["membership_cutoff"] == first_cutoff
    assert (
        _fields(response["view_model"]["sections"][0]["rows"][0]["fields"])["order_id"] == second.pk
    )
    response = _response(
        page,
        _FILLS,
        page.get_by_role("button", name=f"查看订单 {second.pk} 的成交回执", exact=True).click,
    )
    assert response["view_model"]["sections"][0]["rows"] == []
    expect(page.locator("[data-main-panel]")).to_contain_text("空列表不能证明从未成交")
    expect(page.locator("[data-main-panel]")).not_to_contain_text("当前阻断")

    fill_form = _form(page, _FILLS)
    fill_form.locator('[name="account_id"]').select_option(str(book.harness.account.pk))
    fill_form.locator('[name="order_id"]').fill(str(book.order.pk))
    response = _response(page, _FILLS, fill_form.locator(".tui-action-submit").click)
    row = _fields(response["view_model"]["sections"][0]["rows"][0]["fields"])
    assert row["receipt_id"] == book.receipt.pk
    assert row["price"] == str(book.trade.price)
    assert row["recorded_at"] == book.receipt.created_at.isoformat()
    receipt_section = page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text="本页已留存成交回执")
    )
    receipt_section.locator("summary").click()
    price_cell = receipt_section.get_by_role("cell", name=row["price"], exact=True)
    price_cell.scroll_into_view_if_needed()
    expect(price_cell).to_be_visible()
    if page.viewport_size and page.viewport_size["width"] <= 640:
        bounds = page.locator(".tui-main-panel").bounding_box()
        assert bounds and bounds["width"] >= page.viewport_size["width"] * 0.8
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    expect(page.locator("[data-main-panel]")).to_contain_text("模拟成交时刻")
    expect(page.locator("[data-main-panel]")).to_contain_text(row["price"])
    expect(page.locator("[data-main-panel]")).not_to_contain_text("当前阻断")
    page.screenshot(
        path=str(
            Path(settings.BASE_DIR)
            / "artifacts/a-share-usability/ash03-order-recovery-2026-10-29/order-history"
            / f"receipt-visible-{uuid4().hex[:8]}.png"
        )
    )

    secondary_id = _db_call(
        lambda: SimulatedAccountModel.objects.get(
            user_id=book.harness.user_id, account_name="History scope switch"
        ).pk
    )
    fill_form.locator('[name="account_id"]').select_option(str(secondary_id))
    response = _response(page, _FILLS, fill_form.locator(".tui-action-submit").click)
    assert response["response"]["status_code"] == 404
    expect(page.locator("[data-main-panel]")).not_to_contain_text("单条回执已核对")
    expect(page.locator("[data-main-panel]")).to_contain_text("当前账户或订单范围无法访问")
    assert _ledger_state(book) == before
