"""Exercise an owner's Match, history, and separate Apply journey in a real browser."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect

from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedTradeModel,
)
from apps.simulated_trading.interface import owner_order_matching_views, owner_order_operation_views
from tests.component.simulated_trading import (
    test_owner_order_operations_api as owner_operations_api,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF as RESERVATION_AS_OF,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _calendar as _build_calendar,
)
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _FixedClock,
    _reserve,
)
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
from tests.component.simulated_trading.test_owner_order_matching_api import (
    _NEXT_AS_OF,
    _NEXT_INTERVAL_END,
    _NEXT_KNOWN_AT,
    _NEXT_SESSION,
    _create_owner_order_and_binding,
    _no_ledger_state,
    _qualified_fixture,
    _ScenarioQualificationReader,
    build_owner_matching,
)
from tests.component.simulated_trading.test_owner_order_matching_api import (
    owner_match_harness as owner_match_harness,
)
from tests.integration.simulated_trading.test_fee_correction_confirmation_browser import (
    _db_call,
    _form,
    _response,
)
from tests.integration.simulated_trading.test_order_decision_history_browser import (
    _DecisionBrowserSession,
    _financial_state,
)
from tests.integration.simulated_trading.test_order_decision_history_browser import (
    decision_browser as decision_browser,
)
from tests.integration.simulated_trading.test_order_decision_history_browser import (
    decision_scope_account as decision_scope_account,
)
from tests.integration.simulated_trading.test_order_history_browser import _fields

pytestmark = pytest.mark.django_db(transaction=True)

_ORDERS = "simulated-trading.orders"
_MATCH = "simulated-trading.order-match"
_DECISIONS = "simulated-trading.order-decisions"
_APPLY = "simulated-trading.order-decision-apply"


def _open_match_form(
    page: Page,
    *,
    account_id: int,
    order_id: int,
) -> Locator:
    """Open Match from the real order list and verify the date is still required."""

    orders_form = _form(page, _ORDERS)
    orders_form.locator('[name="account_id"]').select_option(str(account_id))
    orders_form.locator('[name="limit"]').fill("100")
    orders = _response(page, _ORDERS, orders_form.locator(".tui-action-submit").click)
    assert orders["response"]["status_code"] == 200
    assert orders["debug"]["raw_available"] is False

    launch = page.get_by_role(
        "button",
        name=f"选择订单 {order_id} 的撮合交易日",
        exact=True,
    )
    missing_date = _response(page, _MATCH, launch.click)
    assert missing_date["response"]["status_code"] == 400
    assert any(field["key"] == "session_date" for field in missing_date["missing_fields"])

    missing_fields_form = page.locator("[data-missing-fields-form]")
    expect(missing_fields_form).to_be_visible()
    missing_fields_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    prompt = _response(
        page,
        _MATCH,
        missing_fields_form.locator('button[type="submit"]').click,
    )
    assert prompt["confirmation_required"] is True
    expect(page.locator(".tui-confirmation")).to_contain_text(f"账户 {account_id}")
    expect(page.locator(".tui-confirmation")).to_contain_text(f"订单 {order_id}")
    expect(page.locator(".tui-confirmation")).to_contain_text(_NEXT_SESSION.isoformat())
    page.locator("[data-cancel-action]").click()
    expect(page.locator("[data-confirm-action]")).not_to_be_visible()

    form = _form(page, _MATCH)
    form.locator('[name="account_id"]').select_option(str(account_id))
    form.locator('[name="order_id"]').fill(str(order_id))
    expect(form.locator('[name="account_id"]')).to_have_value(str(account_id))
    expect(form.locator('[name="order_id"]')).to_have_value(str(order_id))
    return form


def _decision_rows(order_id: int) -> list[LocalDailyMatchModel]:
    """Read persisted decisions for the exact order through the test DB helper."""

    return _db_call(
        lambda: list(
            LocalDailyMatchModel._base_manager.filter(reservation_id=order_id).order_by("pk")
        )
    )


def _owner_order_ledger_state(harness: Any, order: Any) -> object:
    """Read the reservation and financial ledger through the browser DB helper."""

    return _db_call(lambda: _no_ledger_state(harness, order))


@pytest.mark.parametrize(
    "decision_browser",
    [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
    indirect=True,
)
def test_owner_matches_recovers_original_decision_then_separately_applies_it(
    decision_browser: _DecisionBrowserSession,
    order_decision_history_case: _OrderDecisionHistoryCase,
    owner_match_harness: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover one lost Match response, then Apply its original decision exactly once.

    The source qualification is the existing typed fixture, not a live-provider claim.
    """

    case = order_decision_history_case
    assert owner_match_harness.account.pk == case.harness.account.pk
    assert owner_match_harness.user_id == case.harness.user_id
    # Preserve the fixture's two-session settlement rule with enough future days.
    owner_match_harness.preparer._calendar_reader.evidence = _build_calendar(
        as_of=RESERVATION_AS_OF,
        open_dates={date(2026, 10, day) for day in (16, 19, 20, 21, 22)},
        end=date(2026, 10, 22),
    )
    first_order, _owner, _binding = _db_call(
        lambda: _create_owner_order_and_binding(
            owner_match_harness,
            order_key="browser-owner-match-first",
        )
    )
    second_order = _db_call(
        lambda: _reserve(owner_match_harness, order_key="browser-owner-match-second")
    )

    first_qualified = _qualified_fixture(
        first_order,
        session_date=_NEXT_SESSION,
        as_of=_NEXT_AS_OF,
        interval_end_at=_NEXT_INTERVAL_END,
        known_at=_NEXT_KNOWN_AT,
    )
    second_qualified = _qualified_fixture(
        second_order,
        session_date=_NEXT_SESSION,
        as_of=_NEXT_AS_OF,
        interval_end_at=_NEXT_INTERVAL_END,
        known_at=_NEXT_KNOWN_AT,
        identity="browser-owner-match-second-order",
        hash_character="f",
    )
    qualification_reader = _ScenarioQualificationReader(
        (first_qualified, first_qualified, second_qualified, second_qualified)
    )
    monkeypatch.setattr(
        owner_order_matching_views,
        "build_owner_order_matching_use_case",
        lambda: build_owner_matching(
            qualification_reader,
            clock=_FixedClock(_NEXT_AS_OF),
        ),
    )
    monkeypatch.setattr(owner_operations_api, "_APPLY_AT", _NEXT_AS_OF)
    monkeypatch.setattr(
        owner_order_operation_views,
        "build_owner_order_operations_use_case",
        lambda: owner_operations_api.build_owner_operations(case),
    )

    page = decision_browser.page
    before_first_match = _financial_state(case)
    first_order_ledger = _owner_order_ledger_state(owner_match_harness, first_order)

    first_form = _open_match_form(
        page,
        account_id=owner_match_harness.account.pk,
        order_id=first_order.pk,
    )
    match_requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            match_requests.append(request.url)
            if f"/api/tui/actions/{_MATCH}/run/" in request.url
            else None
        ),
    )
    first_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    first_prompt = _response(page, _MATCH, first_form.locator(".tui-action-submit").click)
    assert first_prompt["confirmation_required"] is True
    expect(page.locator("[data-confirm-action]")).to_be_visible()
    expect(page.locator(".tui-confirmation")).to_contain_text(f"订单 {first_order.pk}")
    expect(page.locator(".tui-confirmation")).to_contain_text(_NEXT_SESSION.isoformat())
    state_before_date_change = len(match_requests)

    changed_date = (_NEXT_SESSION + timedelta(days=1)).isoformat()
    first_form.locator('[name="session_date"]').fill(changed_date)
    expect(page.locator("[data-confirm-action]")).not_to_be_visible()
    assert len(match_requests) == state_before_date_change
    assert _decision_rows(first_order.pk) == []
    assert qualification_reader.calls == []
    first_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    first_prompt = _response(page, _MATCH, first_form.locator(".tui-action-submit").click)
    assert first_prompt["confirmation_required"] is True

    committed_match_responses: list[dict[str, Any]] = []

    def lose_committed_match_response(route: Route) -> None:
        """Let the actual TUI/API/ORM path commit, then lose only its browser response."""

        upstream = route.fetch()
        committed_match_responses.append(upstream.json())
        route.abort("failed")

    match_route = f"**/actions/{_MATCH}/run/"
    page.route(match_route, lose_committed_match_response)
    page.locator("[data-confirm-action]").click()
    expect(page.locator("[data-main-panel]")).to_contain_text("暂不能确认")
    page.unroute(match_route, lose_committed_match_response)

    assert len(committed_match_responses) == 1
    committed = committed_match_responses[0]
    assert committed["response"]["status_code"] == 200, committed
    assert committed["outcome"] == "success"
    committed_fields = _fields(committed["view_model"]["fields"])
    assert committed["view_model"]["status"] == "已保存撮合决定"
    assert committed_fields["order_id"] == str(first_order.pk)
    assert committed_fields["session_date"] == _NEXT_SESSION.isoformat()
    assert len(qualification_reader.calls) == 2
    assert _owner_order_ledger_state(owner_match_harness, first_order) == first_order_ledger
    assert len(_decision_rows(first_order.pk)) == 1
    decision = _decision_rows(first_order.pk)[0]
    assert decision.outcome == LocalDailyMatchModel.OUTCOME_MATCHED

    page.screenshot(path=str(decision_browser.evidence_directory / "owner-match-response-lost.png"))
    history_form = _form(page, _DECISIONS)
    history_form.locator('[name="account_id"]').select_option(str(owner_match_harness.account.pk))
    history_form.locator('[name="order_id"]').fill(str(first_order.pk))
    history_form.locator('[name="limit"]').fill("5")
    history = _response(page, _DECISIONS, history_form.locator(".tui-action-submit").click)
    assert history["response"]["status_code"] == 200
    assert history["outcome"] == "success"
    history_row = _fields(history["view_model"]["sections"][0]["rows"][0]["fields"])
    assert history_row["decision_id"] == decision.pk
    assert _fields(history["view_model"]["fields"])["order_id"] == str(first_order.pk)
    assert history_row["outcome"] == "已生成模拟成交"
    assert history_row["posting_state"] == "入账尚未确认"
    assert history_row["session_date"] == _NEXT_SESSION.isoformat()
    assert len(_decision_rows(first_order.pk)) == 1
    assert _financial_state(case) != before_first_match
    assert _owner_order_ledger_state(owner_match_harness, first_order) == first_order_ledger
    expect(page.locator("[data-main-panel]")).to_contain_text("入账尚未确认")
    page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text="本页原撮合决定")
    ).locator("summary").click()
    unconfirmed_cell = page.get_by_role("cell", name="入账尚未确认", exact=True)
    unconfirmed_cell.scroll_into_view_if_needed()
    expect(unconfirmed_cell).to_be_visible()
    page.screenshot(
        path=str(decision_browser.evidence_directory / "owner-original-match-history.png")
    )

    original_read = qualification_reader.read

    def reject_replay_source_read(**kwargs: Any) -> Any:
        command = kwargs["command"]
        assert command.order_idempotency_key != first_order.idempotency_key
        return original_read(**kwargs)

    monkeypatch.setattr(qualification_reader, "read", reject_replay_source_read)
    retry_form = _open_match_form(
        page,
        account_id=owner_match_harness.account.pk,
        order_id=first_order.pk,
    )
    retry_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    retry_prompt = _response(page, _MATCH, retry_form.locator(".tui-action-submit").click)
    assert retry_prompt["confirmation_required"] is True
    replay = _response(page, _MATCH, page.locator("[data-confirm-action]").click)
    assert replay["response"]["status_code"] == 200
    assert replay["outcome"] == "success"
    replay_fields = _fields(replay["view_model"]["fields"])
    assert replay["view_model"]["status"] == "已保存撮合决定"
    assert replay_fields["order_id"] == str(first_order.pk)
    assert replay_fields["session_date"] == _NEXT_SESSION.isoformat()
    assert replay_fields["replayed"] == "是"
    assert len(qualification_reader.calls) == 2
    assert len(_decision_rows(first_order.pk)) == 1
    assert _owner_order_ledger_state(owner_match_harness, first_order) == first_order_ledger

    history_launch = page.get_by_role(
        "button",
        name="核对该订单已保存的撮合决定",
        exact=True,
    )
    history = _response(page, _DECISIONS, history_launch.click)
    history_row = _fields(history["view_model"]["sections"][0]["rows"][0]["fields"])
    assert history_row["decision_id"] == decision.pk
    assert history_row["posting_state"] == "入账尚未确认"
    apply_launch = page.get_by_role(
        "button",
        name=f"按原撮合决定 {decision.pk} 恢复入账",
        exact=True,
    )
    apply_prompt = _response(page, _APPLY, apply_launch.click)
    assert apply_prompt["confirmation_required"] is True
    expect(page.locator(".tui-confirmation")).to_contain_text(f"原撮合决定 {decision.pk}")
    assert _owner_order_ledger_state(owner_match_harness, first_order) == first_order_ledger

    before_apply_trades = _db_call(
        lambda: SimulatedTradeModel._base_manager.filter(
            account_id=owner_match_harness.account.pk
        ).count()
    )
    before_apply_receipts = _db_call(
        lambda: SimulatedOrderFillReceiptModel._base_manager.filter(
            reservation_id=first_order.pk
        ).count()
    )
    applied = _response(page, _APPLY, page.locator("[data-confirm-action]").click)
    assert applied["response"]["status_code"] == 200, applied
    assert applied["outcome"] == "success"
    applied_fields = _fields(applied["view_model"]["fields"])
    assert applied_fields["order_id"] == str(first_order.pk)
    assert applied_fields["decision_id"] == str(decision.pk)
    assert applied["view_model"]["status"] == "原决定已恢复入账"
    assert (
        _db_call(
            lambda: SimulatedTradeModel._base_manager.filter(
                account_id=owner_match_harness.account.pk
            ).count()
        )
        == before_apply_trades + 1
    )
    assert (
        _db_call(
            lambda: SimulatedOrderFillReceiptModel._base_manager.filter(
                reservation_id=first_order.pk
            ).count()
        )
        == before_apply_receipts + 1
    )
    assert len(_decision_rows(first_order.pk)) == 1
    after_apply_first_order = _owner_order_ledger_state(owner_match_harness, first_order)
    assert after_apply_first_order != first_order_ledger

    readback_launch = page.get_by_role(
        "button",
        name="核对该订单原撮合决定",
        exact=True,
    )
    applied_history = _response(page, _DECISIONS, readback_launch.click)
    applied_row = _fields(applied_history["view_model"]["sections"][0]["rows"][0]["fields"])
    assert applied_row["decision_id"] == decision.pk
    assert applied_row["posting_state"] == "已核对原成交回执"
    page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text="本页原撮合决定")
    ).locator("summary").click()
    receipt_cell = page.get_by_role("cell", name="已核对原成交回执", exact=True)
    receipt_cell.scroll_into_view_if_needed()
    expect(receipt_cell).to_be_visible()
    page.screenshot(
        path=str(decision_browser.evidence_directory / "owner-original-decision-applied.png")
    )

    before_second_match = _owner_order_ledger_state(owner_match_harness, second_order)
    second_form = _open_match_form(
        page,
        account_id=owner_match_harness.account.pk,
        order_id=second_order.pk,
    )
    second_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    second_prompt = _response(page, _MATCH, second_form.locator(".tui-action-submit").click)
    assert second_prompt["confirmation_required"] is True
    second_form.locator('[name="session_date"]').fill(changed_date)
    expect(page.locator("[data-confirm-action]")).not_to_be_visible()
    assert len(_decision_rows(second_order.pk)) == 0
    second_form.locator('[name="session_date"]').fill(_NEXT_SESSION.isoformat())
    second_prompt = _response(page, _MATCH, second_form.locator(".tui-action-submit").click)
    assert second_prompt["confirmation_required"] is True

    late_responses: list[dict[str, Any]] = []

    def change_order_before_late_response(route: Route) -> None:
        """Commit the second order, change the visible target, then return its response."""

        upstream = route.fetch()
        late_responses.append(upstream.json())
        second_form.locator('[name="order_id"]').fill(str(first_order.pk))
        route.fulfill(response=upstream)

    page.route(match_route, change_order_before_late_response)
    page.locator("[data-confirm-action]").click()
    expect(second_form.locator('[name="order_id"]')).to_have_value(str(first_order.pk))
    assert len(late_responses) == 1
    assert late_responses[0]["response"]["status_code"] == 200, late_responses[0]
    assert late_responses[0]["outcome"] == "success"
    assert late_responses[0]["view_model"]["status"] == "已保存未撮合决定"
    late_fields = _fields(late_responses[0]["view_model"]["fields"])
    assert late_fields["matched_quantity"] == "0.000000"
    assert late_fields["matched_price"] == "不适用"
    assert late_fields["order_id"] == str(second_order.pk)
    assert late_fields["session_date"] == _NEXT_SESSION.isoformat()
    page.unroute(match_route, change_order_before_late_response)
    expect(page.locator("[data-confirm-action]")).not_to_be_visible()
    expect(page.locator("[data-main-panel]")).not_to_contain_text("已保存撮合决定")
    expect(page.locator("[data-main-panel]")).not_to_contain_text("已保存未撮合决定")

    second_rows = _decision_rows(second_order.pk)
    assert len(second_rows) == 1
    assert second_rows[0].outcome == LocalDailyMatchModel.OUTCOME_NO_MATCH
    assert len(qualification_reader.calls) == 4
    assert _owner_order_ledger_state(owner_match_harness, second_order) == before_second_match
    assert _owner_order_ledger_state(owner_match_harness, first_order) == after_apply_first_order
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if page.viewport_size and page.viewport_size["width"] <= 640:
        bounds = page.locator(".tui-main-panel").bounding_box()
        assert bounds and bounds["width"] >= page.viewport_size["width"] * 0.8
    page.screenshot(
        path=str(decision_browser.evidence_directory / "late-match-does-not-change-target.png")
    )
