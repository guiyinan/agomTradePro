"""Apply fee-aware funding and dependency states to proposed asset actions."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from apps.simulated_trading.application.rebalance_plan_preview_contracts import (
    RebalancePlanPreviewItem,
)
from apps.simulated_trading.application.rebalance_preview_valuation import _decimal_value
from apps.simulated_trading.domain.rebalance_preview_math import round_cny_amount


def known_action_amount(item: RebalancePlanPreviewItem) -> Decimal | None:
    """Return a notional only when constrained quantity, price, and FeeV2 exist."""

    if item.actionable_quantity is None or item.reference_price is None or item.fee is None:
        return None
    return round_cny_amount(item.actionable_quantity * item.reference_price)


def fee_total(item: RebalancePlanPreviewItem) -> Decimal | None:
    """Read an exact FeeV2 total only from a complete row fee payload."""

    return _decimal_value(item.fee.get("total")) if item.fee is not None else None


def sell_fee_cash_reason(
    *,
    sells: list[RebalancePlanPreviewItem],
    available_cash_before: Decimal | None,
) -> str | None:
    """Return a stable blocker when known SELL fees exceed both gross and free cash."""

    if not sells:
        return None
    gross_values = [known_action_amount(item) for item in sells]
    fee_values = [fee_total(item) for item in sells]
    if any(value is None for value in (*gross_values, *fee_values)):
        return None
    deficit = sum(
        (
            max(fee - gross, Decimal("0.00"))
            for gross, fee in zip(gross_values, fee_values, strict=True)
            if gross is not None and fee is not None
        ),
        Decimal("0.00"),
    )
    if deficit == 0:
        return None
    if available_cash_before is None:
        return "SELL_FEE_CASH_UNKNOWN"
    return "SELL_FEE_CASH_SHORTFALL" if deficit > available_cash_before else None


def mark_buys_conditional_on_sales(
    items: list[RebalancePlanPreviewItem],
) -> list[RebalancePlanPreviewItem]:
    """Withhold BUY quantities funded only by estimated, unsettled sale proceeds."""

    return [
        (
            replace(
                item,
                status="conditional",
                actionable_amount=None,
                actionable_quantity=None,
                remaining_quantity=item.suggested_quantity,
                reason_codes=tuple(
                    dict.fromkeys((*item.reason_codes, "BUY_DEPENDS_ON_SETTLED_SALES"))
                ),
            )
            if item.scope == "asset"
            and item.action == "buy"
            and item.status in {"ready", "partial"}
            else item
        )
        for item in items
    ]


def block_buys_for_unknown_funding(
    items: list[RebalancePlanPreviewItem],
) -> list[RebalancePlanPreviewItem]:
    """Do not claim actionable BUY quantities when cash or sale proceeds are unknown."""

    return _block_buys(items, "BUY_FUNDING_UNKNOWN")


def block_buys_for_shortfall(
    items: list[RebalancePlanPreviewItem],
) -> list[RebalancePlanPreviewItem]:
    """Keep suggested BUY amounts visible while withholding unfunded quantities."""

    return _block_buys(items, "CASH_SHORTFALL")


def block_buys_for_incomplete_sells(
    items: list[RebalancePlanPreviewItem],
) -> list[RebalancePlanPreviewItem]:
    """Withhold dependent buys when a requested sale cannot reach its target."""

    return _block_buys(items, "SELL_DEPENDENCY_INCOMPLETE", asset_scope=True)


def block_buys_for_total_position_cap(
    items: list[RebalancePlanPreviewItem],
    reason: str,
) -> list[RebalancePlanPreviewItem]:
    """Withhold every BUY when the existing total-position cap is exceeded or unknown."""

    return [
        (
            replace(
                item,
                status="blocked",
                actionable_amount=None,
                actionable_quantity=None,
                remaining_quantity=item.suggested_quantity,
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, reason))),
            )
            if item.scope == "asset" and item.action == "buy"
            else item
        )
        for item in items
    ]


def block_sells_for_fee_cash(
    items: list[RebalancePlanPreviewItem],
    reason: str,
) -> list[RebalancePlanPreviewItem]:
    """Withhold SELL rows whose known net proceeds need unavailable account cash."""

    return [
        (
            replace(
                item,
                status="blocked",
                actionable_amount=None,
                actionable_quantity=None,
                remaining_quantity=item.suggested_quantity,
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, reason))),
            )
            if item.scope == "asset" and item.action == "sell" and item.status != "blocked"
            else item
        )
        for item in items
    ]


def _block_buys(
    items: list[RebalancePlanPreviewItem],
    reason: str,
    *,
    asset_scope: bool = False,
) -> list[RebalancePlanPreviewItem]:
    """Clear actionable quantities while retaining the desired change and reason."""

    return [
        (
            replace(
                item,
                status="blocked",
                actionable_amount=None,
                actionable_quantity=None,
                remaining_quantity=item.suggested_quantity,
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, reason))),
            )
            if item.action == "buy"
            and item.status != "blocked"
            and (not asset_scope or item.scope == "asset")
            else item
        )
        for item in items
    ]


__all__: tuple[str, ...] = (
    "block_buys_for_incomplete_sells",
    "block_buys_for_shortfall",
    "block_buys_for_total_position_cap",
    "block_buys_for_unknown_funding",
    "block_sells_for_fee_cash",
    "fee_total",
    "known_action_amount",
    "mark_buys_conditional_on_sales",
    "sell_fee_cash_reason",
)
