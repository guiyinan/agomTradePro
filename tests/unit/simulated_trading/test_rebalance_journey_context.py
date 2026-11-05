"""Synthetic-port tests for real paired-read consistency and write qualification."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    PortfolioRiskAccountScope,
)
from apps.simulated_trading.application.rebalance_journey_read_consistency import (
    plan_preview_reservation_read_reasons,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview
from tests.unit.simulated_trading import test_portfolio_risk_service as fixtures
from tests.unit.simulated_trading.test_rebalance_preview_sell_integrity import (
    _finish,
    _preview_item,
)


def _preview() -> RebalancePlanPreview:
    snapshot = fixtures._snapshot()
    row = replace(
        _preview_item(
            action="sell",
            asset_code=fixtures._ASSET_CODE,
            status="ready",
            suggested=Decimal("10"),
            actionable=Decimal("10"),
            fee={"total": "1"},
            sellable=Decimal("87"),
        ),
        identity={"security_id": fixtures._SECURITY_ID},
        current_quantity=Decimal("100"),
        reserved_sell_quantity=Decimal("3"),
    )
    return replace(
        _finish([row]),
        as_of=fixtures._AS_OF,
        financial_snapshot_read_at=snapshot.read_at - timedelta(seconds=1),
        cash_before=Decimal("10000"),
        reserved_cash=Decimal("25"),
        available_cash_before=Decimal("9975"),
    )


def test_paired_reads_compare_financial_state_without_fabricating_equal_times() -> None:
    harness = fixtures._harness()
    preview = _preview()
    prepared = harness.service.prepare_plan_context(
        user_id=fixtures._OWNER_ID, account_id=fixtures._ACCOUNT_ID, preview=preview
    )
    assert preview.financial_snapshot_read_at != prepared.snapshot.read_at
    assert plan_preview_reservation_read_reasons(preview, prepared) == ()
    assert not any(check["dimension"] == "preview_binding" for check in prepared.report["checks"])
    assert harness.writer.records == []


def test_changed_reservations_and_t1_sellable_balance_do_not_hide_behind_equal_cash() -> None:
    original = fixtures._snapshot()
    changed_sell = replace(original.active_orders[1], remaining_quantity=Decimal("4"))
    harness = fixtures._harness(
        snapshot=replace(original, active_orders=(original.active_orders[0], changed_sell))
    )
    prepared = harness.service.prepare_plan_context(
        user_id=fixtures._OWNER_ID, account_id=fixtures._ACCOUNT_ID, preview=_preview()
    )
    reasons = plan_preview_reservation_read_reasons(_preview(), prepared)
    assert "REBALANCE_PLAN_RESERVED_SELL_CHANGED" in reasons
    assert "REBALANCE_PLAN_SELLABLE_QUANTITY_CHANGED" in reasons
    assert prepared.report["must_not_use_for_decision"] is True


def test_reserved_cash_unknown_is_not_zero_and_waiting_sales_never_supply_it() -> None:
    original = fixtures._snapshot()
    unknown = replace(original.active_orders[0], remaining_cash=None)
    harness = fixtures._harness(
        snapshot=replace(original, active_orders=(unknown, original.active_orders[1]))
    )
    prepared = harness.service._contexts.prepare(
        user_id=fixtures._OWNER_ID, account_id=fixtures._ACCOUNT_ID
    )
    assert "REBALANCE_PLAN_RESERVED_CASH_UNKNOWN" in plan_preview_reservation_read_reasons(
        _preview(), prepared
    )


def test_deferred_buy_qualifies_target_sources_without_proposing_an_unfunded_order() -> None:
    harness = fixtures._harness()
    preview = _preview()
    deferred = replace(
        preview.asset_items[0],
        action="buy",
        status="conditional",
        actionable_quantity=None,
        actionable_amount=None,
        reason_codes=("BUY_DEPENDS_ON_SETTLED_SALES",),
    )
    prepared = harness.service.prepare_plan_context(
        user_id=fixtures._OWNER_ID,
        account_id=fixtures._ACCOUNT_ID,
        preview=replace(preview, asset_items=(deferred,)),
    )
    assert prepared.proposals == ()
    assert prepared.assets.assets
    assert not any(check["dimension"] == "preview_binding" for check in prepared.report["checks"])


def test_read_only_scope_cannot_obtain_write_qualified_plan_context() -> None:
    harness = fixtures._harness(
        scope=PortfolioRiskAccountScope(
            owner_user_id=fixtures._OWNER_ID, can_read=True, can_write=False
        )
    )
    with pytest.raises(PortfolioRiskAccountAccessDenied):
        harness.service.prepare_plan_context(
            user_id=fixtures._OWNER_ID, account_id=fixtures._ACCOUNT_ID, preview=_preview()
        )
