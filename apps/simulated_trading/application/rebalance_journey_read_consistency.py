"""Compare real paired reads without rewriting either financial read clock."""

from __future__ import annotations

from decimal import Decimal

from apps.simulated_trading.application.portfolio_risk_context import PreparedPortfolioRisk
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview


def plan_preview_reservation_read_reasons(
    preview: RebalancePlanPreview, prepared: PreparedPortfolioRisk
) -> tuple[str, ...]:
    """Keep unavailable or changed effective reservations out of a trusted plan.

    The existing preview comparison owns cash and held-quantity equality. These
    additional checks compare actual occupied resources, not estimated SELL
    proceeds, and deliberately do not demand identical observation timestamps.
    """

    snapshot = prepared.snapshot
    reasons: list[str] = []
    original_read = preview.financial_snapshot_read_at
    if original_read is None or snapshot.read_at < original_read:
        reasons.append("REBALANCE_PLAN_FINANCIAL_READ_CLOCK_INVALID")
    if not snapshot.active_orders_complete:
        reasons.append("REBALANCE_PLAN_RESERVATION_COVERAGE_UNKNOWN")
    cash_values = tuple(order.remaining_cash for order in snapshot.active_orders)
    if any(value is None for value in cash_values):
        reasons.append("REBALANCE_PLAN_RESERVED_CASH_UNKNOWN")
    else:
        reserved = sum((value for value in cash_values if value is not None), Decimal("0"))
        if preview.reserved_cash is None or preview.reserved_cash != reserved:
            reasons.append("REBALANCE_PLAN_RESERVED_CASH_CHANGED")
        if (
            snapshot.cash is None
            or preview.available_cash_before is None
            or preview.available_cash_before != snapshot.cash - reserved
        ):
            reasons.append("REBALANCE_PLAN_AVAILABLE_CASH_CHANGED")
    for row in preview.asset_items:
        if row.action != "sell":
            continue
        security_id = row.identity.get("security_id") if row.identity is not None else None
        quantities = tuple(
            order.remaining_quantity
            for order in snapshot.active_orders
            if order.side == "sell"
            and order.asset_code == row.asset_code
            and order.security_id == security_id
        )
        if any(value is None for value in quantities):
            reasons.append("REBALANCE_PLAN_RESERVED_SELL_UNKNOWN")
        elif row.reserved_sell_quantity is None or row.reserved_sell_quantity != sum(
            (value for value in quantities if value is not None), Decimal("0")
        ):
            reasons.append("REBALANCE_PLAN_RESERVED_SELL_CHANGED")
        available_values = tuple(
            holding.available_quantity
            for holding in snapshot.holdings
            if holding.asset_code == row.asset_code
            and type(security_id) is str
            and _holding_source_security_id(
                asset_code=holding.asset_code,
                ledger_security_id=holding.security_id,
                prepared=prepared,
            )
            == security_id
        )
        if not available_values or any(value is None for value in available_values):
            reasons.append("REBALANCE_PLAN_SELLABLE_QUANTITY_UNKNOWN")
        elif row.sellable_quantity is None or row.sellable_quantity != (
            sum((value for value in available_values if value is not None), Decimal("0"))
            - sum((value for value in quantities if value is not None), Decimal("0"))
        ):
            reasons.append("REBALANCE_PLAN_SELLABLE_QUANTITY_CHANGED")
    return tuple(dict.fromkeys(reasons))


def _holding_source_security_id(
    *,
    asset_code: str,
    ledger_security_id: str | None,
    prepared: PreparedPortfolioRisk,
) -> str | None:
    """Resolve a missing ledger ID only through one already-qualified identity proof."""

    if ledger_security_id is not None:
        return ledger_security_id
    bindings = tuple(
        binding for binding in prepared.identity_bindings if binding.asset_code == asset_code
    )
    if len(bindings) != 1:
        return None
    binding = bindings[0]
    if binding.ledger_security_id is not None or binding.basis != "pinned_policy_source_mapping":
        return None
    return binding.source_security_id
