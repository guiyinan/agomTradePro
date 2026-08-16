"""Pure domain services for broker execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from .entities import LiveOrderSide, LiveOrderType, OrderApprovalSnapshot
from .rules import build_approval_digest


def _required_int(value: object, *, field_name: str) -> int:
    """Return one required integer projection field."""

    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _sorted_string_items(value: object, *, field_name: str) -> tuple[str, ...]:
    """Normalize one JSON array projection field for stable hashing."""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be an array")
    return tuple(sorted(str(item) for item in value))


def approval_snapshot_for_order(order: Mapping[str, object]) -> OrderApprovalSnapshot:
    """Build the single canonical approval snapshot from an order projection."""

    expires_at = order.get("expires_at")
    if isinstance(expires_at, datetime):
        expires_text = expires_at.isoformat()
    else:
        expires_text = str(expires_at or "")
    limit_price_raw = order.get("limit_price")
    risk_snapshot_json = json.dumps(
        order.get("risk_snapshot") or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return OrderApprovalSnapshot(
        account_id=_required_int(order.get("account_id"), field_name="account_id"),
        agent_id=str(order.get("agent_id") or ""),
        asset_code=str(order["asset_code"]),
        market=str(order.get("market") or ""),
        side=LiveOrderSide(str(order["side"])),
        order_type=LiveOrderType(str(order["order_type"])),
        quantity=Decimal(str(order["quantity"])),
        limit_price=(Decimal(str(limit_price_raw)) if limit_price_raw not in (None, "") else None),
        estimated_amount=Decimal(str(order["estimated_amount"])),
        expires_at=expires_text,
        risk_policy_version=str(order.get("risk_policy_version") or ""),
        risk_snapshot_json=risk_snapshot_json,
        approval_mode=str(order.get("approval_mode") or ""),
        source_recommendation_ids=_sorted_string_items(
            order.get("source_recommendation_ids"),
            field_name="source_recommendation_ids",
        ),
        source_signal_ids=_sorted_string_items(
            order.get("source_signal_ids"),
            field_name="source_signal_ids",
        ),
    )


def approval_digest_for_order(order: Mapping[str, object]) -> str:
    """Build the immutable approval digest from the canonical snapshot."""

    return build_approval_digest(approval_snapshot_for_order(order))


__all__ = ["approval_digest_for_order", "approval_snapshot_for_order"]
