"""Real owner recovery after a lost posting response, then cancellation of the remainder."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Route, expect

from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from apps.simulated_trading.interface import owner_order_operation_views
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

pytestmark = pytest.mark.django_db(transaction=True)
APPLY = "simulated-trading.order-decision-apply"
CANCEL = "simulated-trading.order-cancel"
DECISIONS = "simulated-trading.order-decisions"


@pytest.mark.parametrize(
    "decision_browser",
    [{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
    indirect=True,
)
def test_owner_recovers_original_posting_then_cancels_only_remaining_shares(
    decision_browser: _DecisionBrowserSession,
    order_decision_history_case: _OrderDecisionHistoryCase,
    decision_scope_account: SimulatedAccountModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel confirmation, lose a real committed response, read back, retry, and cancel 90."""
    from tests.component.simulated_trading.test_owner_order_operations_api import (
        build_owner_operations,
    )

    page = decision_browser.page
    case = order_decision_history_case
    use_case = build_owner_operations(case)
    monkeypatch.setattr(
        owner_order_operation_views, "build_owner_order_operations_use_case", lambda: use_case
    )
    decision_id = _db_call(
        lambda: LocalDailyMatchModel._base_manager.get(
            reservation_id=case.order.pk, operation_key=case.matched.command.operation_key
        ).pk
    )
    before = _financial_state(case)
    form = _form(page, APPLY)
    form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    form.locator('[name="order_id"]').fill(str(case.order.pk))
    form.locator('[name="decision_id"]').fill(str(decision_id))
    prompt = _response(page, APPLY, form.locator(".tui-action-submit").click)
    assert prompt["confirmation_required"] is True
    expect(page.locator("[data-confirm-action]")).to_be_visible()
    expect(page.locator(".tui-confirmation")).to_contain_text(f"账户 {case.harness.account.pk}")
    expect(page.locator(".tui-confirmation")).to_contain_text(f"订单 {case.order.pk}")
    expect(page.locator(".tui-confirmation")).to_contain_text(f"原撮合决定 {decision_id}")
    assert _financial_state(case) == before
    form.locator('[name="account_id"]').select_option(str(decision_scope_account.pk))
    expect(page.locator("[data-confirm-action]")).not_to_be_visible()
    assert _financial_state(case) == before
    form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    assert _response(page, APPLY, form.locator(".tui-action-submit").click)["confirmation_required"]
    page.locator("[data-cancel-action]").click()
    assert _financial_state(case) == before

    prompt = _response(page, APPLY, form.locator(".tui-action-submit").click)
    assert prompt["confirmation_required"] is True
    committed_responses: list[dict[str, Any]] = []

    def lose_committed_response(route: Route) -> None:
        upstream = route.fetch()
        committed_responses.append(upstream.json())
        route.abort("failed")

    pattern = f"**/actions/{APPLY}/run/"
    page.route(pattern, lose_committed_response)
    page.locator("[data-confirm-action]").click()
    expect(page.locator("[data-main-panel]")).to_contain_text("暂不能确认")
    assert len(committed_responses) == 1
    assert committed_responses[0]["response"]["status_code"] == 200
    assert committed_responses[0]["outcome"] == "success"
    page.unroute(pattern, lose_committed_response)
    after_apply = _financial_state(case)
    assert after_apply != before
    page.screenshot(
        path=str(decision_browser.evidence_directory / "owner-posting-response-lost.png")
    )

    history_form = _form(page, DECISIONS)
    history_form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    history_form.locator('[name="order_id"]').fill(str(case.order.pk))
    readback = _response(page, DECISIONS, history_form.locator(".tui-action-submit").click)
    assert readback["response"]["status_code"] == 200
    assert readback["outcome"] == "success"
    section = page.locator("[data-detail-section]").filter(
        has=page.locator("summary", has_text="本页原撮合决定")
    )
    section.locator("summary").click()
    receipt_state = section.get_by_role("cell", name="已核对原成交回执", exact=True)
    receipt_state.scroll_into_view_if_needed()
    expect(receipt_state).to_be_visible()
    page.screenshot(path=str(decision_browser.evidence_directory / "owner-original-receipt.png"))
    assert _financial_state(case) == after_apply

    form = _form(page, APPLY)
    form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    form.locator('[name="order_id"]').fill(str(case.order.pk))
    form.locator('[name="decision_id"]').fill(str(decision_id))
    assert _response(page, APPLY, form.locator(".tui-action-submit").click)["confirmation_required"]
    replay = _response(page, APPLY, page.locator("[data-confirm-action]").click)
    assert replay["response"]["status_code"] == 200
    assert replay["outcome"] == "success"
    assert _financial_state(case) == after_apply

    cancel_form = _form(page, CANCEL)
    cancel_form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    cancel_form.locator('[name="order_id"]').fill(str(case.order.pk))
    assert _response(page, CANCEL, cancel_form.locator(".tui-action-submit").click)[
        "confirmation_required"
    ]
    late_cancels: list[dict[str, Any]] = []

    def change_scope_before_cancel_response(route: Route) -> None:
        upstream = route.fetch()
        late_cancels.append(upstream.json())
        cancel_form.locator('[name="account_id"]').select_option(str(decision_scope_account.pk))
        route.fulfill(response=upstream)

    cancel_pattern = f"**/actions/{CANCEL}/run/"
    page.route(cancel_pattern, change_scope_before_cancel_response)
    page.locator("[data-confirm-action]").click()
    expect(cancel_form.locator('[name="account_id"]')).to_have_value(str(decision_scope_account.pk))
    assert len(late_cancels) == 1
    assert late_cancels[0]["response"]["status_code"] == 200
    expect(page.locator("[data-main-panel]")).not_to_contain_text("90.000000")
    page.unroute(cancel_pattern, change_scope_before_cancel_response)
    after_late_cancel = _financial_state(case)
    assert after_late_cancel != after_apply
    cancel_form.locator('[name="account_id"]').select_option(str(case.harness.account.pk))
    assert _response(page, CANCEL, cancel_form.locator(".tui-action-submit").click)[
        "confirmation_required"
    ]
    cancelled = _response(page, CANCEL, page.locator("[data-confirm-action]").click)
    assert cancelled["response"]["status_code"] == 200
    assert cancelled["outcome"] == "success"
    assert _financial_state(case) == after_late_cancel
    expect(page.locator("[data-main-panel]")).to_contain_text("90.000000")
    expect(page.locator("[data-main-panel]")).to_contain_text("累计")
    released_shares = page.locator("[data-main-panel]").get_by_text("90.000000", exact=True)
    released_shares.scroll_into_view_if_needed()
    expect(released_shares).to_be_in_viewport()
    page.screenshot(path=str(decision_browser.evidence_directory / "owner-remainder-cancelled.png"))
    after_cancel = _financial_state(case)
    assert after_cancel != after_apply
    assert _response(page, CANCEL, cancel_form.locator(".tui-action-submit").click)[
        "confirmation_required"
    ]
    repeated = _response(page, CANCEL, page.locator("[data-confirm-action]").click)
    assert repeated["outcome"] == "success"
    assert _financial_state(case) == after_cancel

    cancel_form.locator('[name="account_id"]').select_option(str(decision_scope_account.pk))
    assert _response(page, CANCEL, cancel_form.locator(".tui-action-submit").click)[
        "confirmation_required"
    ]
    refused = _response(page, CANCEL, page.locator("[data-confirm-action]").click)
    assert refused["response"]["status_code"] == 404
    # The workbench reports HTTP failures separately from the blocked user view.
    assert refused["outcome"] == "failed"
    assert refused["view_model"]["outcome"] == "blocked"
    assert refused["view_model"]["fields"] == []
    assert refused["view_model"]["sections"] == []
    expect(page.locator("[data-main-panel]")).not_to_contain_text("90.000000")
    assert _financial_state(case) == after_cancel
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
