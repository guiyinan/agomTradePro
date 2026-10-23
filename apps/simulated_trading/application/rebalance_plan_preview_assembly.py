"""Assemble the final read-only rebalance preview from validated row estimates."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    RebalancePlanRiskContext,
    StrategyPolicyApplicability,
)
from apps.simulated_trading.application.rebalance_preview_funding import (
    block_buys_for_incomplete_sells,
    block_buys_for_shortfall,
    block_buys_for_total_position_cap,
    block_buys_for_unknown_funding,
    block_sells_for_fee_cash,
    fee_total,
    known_action_amount,
    mark_buys_conditional_on_sales,
    sell_fee_cash_reason,
)
from apps.simulated_trading.domain.rebalance_preview_math import (
    account_total_position_cap_reason,
    estimate_plan_funding,
    strategy_total_position_cap_reason,
)


def finish_rebalance_plan_preview(
    *,
    cutoff: datetime,
    financial_snapshot_read_at: datetime,
    portfolio_value: Decimal | None,
    cash_before: Decimal | None,
    reserved_cash: Decimal | None,
    available_cash_before: Decimal | None,
    projected_position_amount: Decimal | None,
    max_total_position_pct: Decimal | None,
    account_max_total_position_pct: Decimal | None,
    strategy_policy_applicability: StrategyPolicyApplicability,
    reason_codes: tuple[str, ...],
    allocation_items: tuple[RebalancePlanPreviewItem, ...],
    items: list[RebalancePlanPreviewItem],
    risk_context: RebalancePlanRiskContext,
) -> RebalancePlanPreview:
    """Apply funding dependencies and return the complete preview contract."""

    sells = [item for item in items if item.scope == "asset" and item.action == "sell"]
    buys = [item for item in items if item.scope == "asset" and item.action == "buy"]
    unresolved_targets = [
        item
        for item in items
        if item.scope == "asset"
        and item.action == "blocked"
        and item.status == "blocked"
        and item.target_mode in {"strategy_rule", "user_target_difference"}
    ]
    if buys and any(item.status != "ready" for item in sells):
        items = block_buys_for_incomplete_sells(items)
        buys = [item for item in items if item.scope == "asset" and item.action == "buy"]
    # An unresolved target may affect either side; never treat it as zero activity.
    sell_gross_values = [known_action_amount(item) for item in sells] + [None] * len(
        unresolved_targets
    )
    sell_fee_values = [fee_total(item) for item in sells] + [None] * len(unresolved_targets)
    buy_gross_values = [known_action_amount(item) for item in buys] + [None] * len(
        unresolved_targets
    )
    buy_fee_values = [fee_total(item) for item in buys] + [None] * len(unresolved_targets)
    funding = estimate_plan_funding(
        cash_before=available_cash_before,
        sell_gross_values=tuple(sell_gross_values),
        sell_fee_values=tuple(sell_fee_values),
        buy_gross_values=tuple(buy_gross_values),
        buy_fee_values=tuple(buy_fee_values),
    )
    action_rows = [
        item for item in items if item.scope == "asset" and item.action in {"buy", "sell"}
    ]
    action_fees = [fee_total(item) for item in action_rows]
    known_action_fees = tuple(value for value in action_fees if value is not None)
    projected_equity = (
        portfolio_value - sum(known_action_fees, Decimal("0.00"))
        if portfolio_value is not None
        and len(known_action_fees) == len(action_fees)
        and not unresolved_targets
        else None
    )
    if buys:
        strategy_cap_reason = (
            strategy_total_position_cap_reason(
                action="buy",
                projected_position_amount=projected_position_amount,
                projected_equity=projected_equity,
                max_total_position_pct=max_total_position_pct,
            )
            if strategy_policy_applicability != "not_applicable"
            else None
        )
        cap_reasons = (
            strategy_cap_reason,
            account_total_position_cap_reason(
                action="buy",
                projected_position_amount=projected_position_amount,
                projected_equity=projected_equity,
                max_total_position_pct=account_max_total_position_pct,
            ),
        )
        for total_cap_reason in cap_reasons:
            if total_cap_reason is not None:
                items = block_buys_for_total_position_cap(items, total_cap_reason)
        buys = [item for item in items if item.scope == "asset" and item.action == "buy"]

    sell_fee_shortfall = sell_fee_cash_reason(
        sells=sells,
        available_cash_before=available_cash_before,
    )
    if sell_fee_shortfall is not None:
        items = block_sells_for_fee_cash(items, sell_fee_shortfall)
        if buys:
            items = block_buys_for_incomplete_sells(items)
            buys = [item for item in items if item.scope == "asset" and item.action == "buy"]

    if funding.status == "unknown":
        items = block_buys_for_unknown_funding(items)
    elif funding.status == "shortfall":
        items = block_buys_for_shortfall(items)

    funding_status: Literal["known", "shortfall", "unknown", "conditional"] = funding.status
    buy_depends_on_settled_sales = sell_fee_shortfall is None and bool(sells and buys)
    if buy_depends_on_settled_sales and funding.status == "known":
        items = mark_buys_conditional_on_sales(items)
        funding_status = "conditional"

    asset_items = [item for item in items if item.scope == "asset"]
    if not asset_items or all(item.action == "hold" for item in asset_items):
        status = "no_rebalance_required"
    elif any(item.status == "blocked" for item in items) and any(
        item.status in {"ready", "partial", "conditional"} for item in items
    ):
        status = "partial"
    elif any(item.status == "blocked" for item in items):
        status = "blocked"
    elif funding_status == "conditional":
        status = "conditional"
    elif any(item.status in {"ready", "partial"} for item in items):
        status = "partial" if any(item.status == "blocked" for item in items) else "ready"
    else:
        status = "blocked"
    return RebalancePlanPreview(
        status=status,
        reason_codes=reason_codes,
        as_of=cutoff,
        financial_snapshot_read_at=financial_snapshot_read_at,
        portfolio_value=portfolio_value,
        cash_before=cash_before,
        reserved_cash=reserved_cash,
        available_cash_before=available_cash_before,
        projected_cash_after_sells=funding.cash_after_sells,
        estimated_sell_gross=funding.sell_gross,
        estimated_sell_fees=funding.sell_fees,
        estimated_sell_net=funding.sell_net,
        estimated_buy_gross=funding.buy_gross,
        estimated_buy_fees=funding.buy_fees,
        estimated_buy_total=funding.buy_total,
        projected_cash_after_buys=funding.cash_after_buys,
        funding_status=funding_status,
        sell_before_buy={
            "required": bool(sells and buys),
            "sell_asset_codes": [item.asset_code for item in sells],
            "buy_asset_codes": [item.asset_code for item in buys],
            "sequence": "sell_then_buy",
            "buy_requires_settled_sales": buy_depends_on_settled_sales,
        },
        risk_context=risk_context,
        allocation_items=allocation_items,
        asset_items=tuple(items),
    )


__all__: tuple[str, ...] = ("finish_rebalance_plan_preview",)
