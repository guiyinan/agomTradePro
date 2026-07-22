"""Pure domain services for broker execution."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .entities import LiveOrderSide, LiveOrderType, OrderApprovalSnapshot
from .rules import build_approval_digest


def approval_digest_for_order(order: dict[str, object]) -> str:
    """Build the immutable approval digest from an order projection."""

    expires_at = order.get("expires_at")
    if isinstance(expires_at, datetime):
        expires_text = expires_at.isoformat()
    else:
        expires_text = str(expires_at or "")
    limit_price_raw = order.get("limit_price")
    snapshot = OrderApprovalSnapshot(
        account_id=int(order["account_id"]),
        asset_code=str(order["asset_code"]),
        side=LiveOrderSide(str(order["side"])),
        order_type=LiveOrderType(str(order["order_type"])),
        quantity=Decimal(str(order["quantity"])),
        limit_price=(
            Decimal(str(limit_price_raw)) if limit_price_raw not in (None, "") else None
        ),
        expires_at=expires_text,
        risk_policy_version=str(order.get("risk_policy_version") or ""),
        source_recommendation_ids=tuple(
            sorted(str(item) for item in (order.get("source_recommendation_ids") or []))
        ),
        source_signal_ids=tuple(
            sorted(str(item) for item in (order.get("source_signal_ids") or []))
        ),
    )
    return build_approval_digest(snapshot)
