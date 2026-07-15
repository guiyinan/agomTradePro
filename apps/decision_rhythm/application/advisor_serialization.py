"""Serialization and numeric normalization helpers for advisor payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def _build_decision_card_payload(order: dict[str, Any]) -> dict[str, Any]:
    current_weight = _to_decimal(order.get("current_weight"))
    target_weight = _to_decimal(order.get("target_weight"))
    return {
        "order_intent_id": order.get("order_intent_id"),
        "asset_code": order.get("asset_code"),
        "asset_name": order.get("asset_name"),
        "action": order.get("side"),
        "confidence": _decision_confidence(order),
        "current_weight": order.get("current_weight"),
        "target_weight": order.get("target_weight"),
        "delta_weight": _decimal_to_number(target_weight - current_weight),
        "estimated_amount": order.get("estimated_amount"),
        "primary_reasons": [order.get("reason") or "账户规则生成。"],
        "counter_reasons": list(order.get("risk_notes") or []),
        "invalidation_logic": order.get("invalidation_rule"),
        "valid_until": None,
        "data_asof": order.get("data_asof") or {},
        "risk_notes": list(order.get("risk_notes") or []),
        "risk_gate_status": order.get("risk_gate_status"),
        "blocking_status": order.get("blocking_status"),
        "source_recommendation_ids": list(order.get("source_recommendation_ids") or []),
        "conflict_resolution": order.get("conflict_resolution") or {},
        "tracking": order.get("tracking") or {},
        "confirmation": order.get("confirmation") or {},
        "expected_loss_if_wrong": _expected_loss_if_wrong(order),
    }


def _decision_confidence(order: dict[str, Any]) -> float:
    if order.get("blocking_status") != "OK":
        return 0.0
    if order.get("risk_gate_status") == "REVIEW":
        return 0.45
    if order.get("side") == "HOLD":
        return 0.5
    return 0.65


def _expected_loss_if_wrong(order: dict[str, Any]) -> float | None:
    amount = _to_decimal(order.get("estimated_amount"))
    if amount <= 0:
        return 0.0
    return _decimal_to_number(amount * Decimal("0.05"))


def _normalize_percent(value: Any) -> Decimal:
    pct = _to_decimal(value)
    if abs(pct) <= Decimal("1"):
        return pct * Decimal("100")
    return pct


def _to_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    decimal_value = _to_decimal(value)
    return decimal_value


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return _to_decimal(value)


def _decimal_to_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _serialize_time(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _now_iso() -> str:

    return datetime.now(UTC).isoformat()


__all__ = [
    "_build_decision_card_payload",
    "_decision_confidence",
    "_expected_loss_if_wrong",
    "_normalize_percent",
    "_to_decimal",
    "_optional_decimal",
    "_to_decimal_or_none",
    "_decimal_to_number",
    "_serialize_time",
    "_now_iso",
]
