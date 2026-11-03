"""Preserve incomplete target configuration in a read-only blocked preview."""

from __future__ import annotations

from datetime import datetime

from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreview,
    RebalancePlanPreviewItem,
    RebalancePlanRiskContext,
)


def _blocked_preview(
    *,
    as_of: datetime,
    financial_snapshot_read_at: datetime | None = None,
    reason_codes: tuple[str, ...],
    risk_context: RebalancePlanRiskContext,
    allocation_items: tuple[RebalancePlanPreviewItem, ...],
) -> RebalancePlanPreview:
    """Keep invalid target configuration visible without inventing asset rows."""

    return RebalancePlanPreview(
        status="blocked",
        reason_codes=reason_codes,
        as_of=as_of,
        financial_snapshot_read_at=financial_snapshot_read_at,
        portfolio_value=None,
        cash_before=None,
        reserved_cash=None,
        available_cash_before=None,
        projected_cash_after_sells=None,
        estimated_sell_gross=None,
        estimated_sell_fees=None,
        estimated_sell_net=None,
        estimated_buy_gross=None,
        estimated_buy_fees=None,
        estimated_buy_total=None,
        projected_cash_after_buys=None,
        funding_status="unknown",
        sell_before_buy={
            "required": False,
            "sell_asset_codes": [],
            "buy_asset_codes": [],
            "sequence": "sell_then_buy",
        },
        risk_context=risk_context,
        allocation_items=allocation_items,
        asset_items=(),
    )
