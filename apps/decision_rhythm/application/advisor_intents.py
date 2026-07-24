"""Order-intent normalization, invalidation, and decision-card helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from apps.decision_rhythm.application.advisor_contracts import (
    AdvisorOrderIntent,
)
from apps.decision_rhythm.application.advisor_serialization import (
    _decimal_to_number,
    _optional_decimal,
    _to_decimal,
)


def _failed_execution_checks(checks: dict[str, Any]) -> list[dict[str, str]]:
    failed: list[dict[str, str]] = []
    for key, payload in checks.items():
        if not isinstance(payload, dict):
            continue
        if payload.get("passed", True) is False:
            failed.append(
                {
                    "key": key,
                    "reason": str(payload.get("reason") or payload.get("blocked_reason") or key),
                }
            )
    return failed


def _build_signal_invalidation_check(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    invalidated: list[dict[str, Any]] = []
    missing_rules: list[str] = []
    for signal_id, payload in payloads.items():
        status = str(payload.get("status") or "").lower()
        invalidated_at = payload.get("invalidated_at")
        if status == "invalidated" or invalidated_at:
            invalidated.append(
                {
                    "signal_id": signal_id,
                    "status": status or "invalidated",
                    "invalidated_at": invalidated_at,
                }
            )
        if not (
            payload.get("invalidation_rule_json")
            or payload.get("invalidation_description")
            or payload.get("invalidation_logic")
        ):
            missing_rules.append(signal_id)

    passed = not invalidated
    reason = ""
    if invalidated:
        reason = "来源信号已被证伪: " + ", ".join(str(item["signal_id"]) for item in invalidated)
    return {
        "passed": passed,
        "reason": reason,
        "invalidated": invalidated,
        "missing_invalidation_rules": missing_rules,
        "checked_signal_ids": list(payloads),
    }


def _recommendation_asset_code(recommendation: Any | None) -> str:
    if recommendation is None:
        return ""
    return (
        str(
            getattr(recommendation, "security_code", "")
            or getattr(recommendation, "asset_code", "")
            or ""
        )
        .strip()
        .upper()
    )


def _normalize_recommendation_side(recommendation: Any | None) -> str:
    if recommendation is None:
        return ""
    side = str(getattr(recommendation, "side", "") or "").strip().upper()
    if side == "SELL":
        return "EXIT"
    return side


def _recommendation_id(recommendation: Any | None) -> str:
    if recommendation is None:
        return ""
    return str(getattr(recommendation, "recommendation_id", "") or "")


def _recommendation_source_signal_ids(recommendation: Any | None) -> list[str]:
    if recommendation is None:
        return []
    return [str(item) for item in (getattr(recommendation, "source_signal_ids", []) or [])]


def _recommendation_source_candidate_ids(recommendation: Any | None) -> list[str]:
    if recommendation is None:
        return []
    return [str(item) for item in (getattr(recommendation, "source_candidate_ids", []) or [])]


def _recommendation_reason(recommendation: Any | None) -> str:
    if recommendation is None:
        return "账户规则生成。"
    return str(
        getattr(recommendation, "human_rationale", "")
        or getattr(recommendation, "reason", "")
        or "来自工作台统一推荐。"
    )


def _invalidation_rule(recommendation: Any | None) -> str:
    if recommendation is None:
        return "若宏观环境、Beta Gate 或标的基本面发生反向变化，重新评估。"
    stop_loss = _optional_decimal(getattr(recommendation, "stop_loss_price", None))
    if stop_loss and stop_loss > 0:
        return f"跌破止损价 {stop_loss} 或推荐失效时重新评估。"
    return "若推荐信号失效、Beta Gate 不通过或价格偏离入场区间，暂停执行。"


def _recommendation_price(recommendation: Any) -> Decimal | None:
    for attr in ("current_price", "entry_price_high", "fair_value", "entry_price_low"):
        value = _optional_decimal(getattr(recommendation, attr, None))
        if value is not None and value > 0:
            return value
    return None


def _recommended_target_weight(recommendation: Any, *, baseline: str) -> Decimal:
    raw_pct = _to_decimal(getattr(recommendation, "position_pct", 0))
    if raw_pct > 1:
        raw_pct = raw_pct / Decimal("100")
    default_weight = Decimal("0.08") if baseline == "empty_positions" else Decimal("0.05")
    weight = raw_pct if raw_pct > 0 else default_weight
    return min(max(weight, Decimal("0.02")), Decimal("0.15"))


def _target_quantity(
    *, total_asset: Decimal, target_weight: Decimal, price: Decimal | None
) -> Decimal:
    if price is None or price <= 0:
        return Decimal("0")
    return _floor_quantity((total_asset * target_weight) / price)


def _floor_quantity(value: Decimal) -> Decimal:
    if value <= 0:
        return Decimal("0")
    return value.quantize(Decimal("1"), rounding=ROUND_FLOOR)


def _price_band(price: Decimal | None) -> dict[str, Any]:
    if price is None or price <= 0:
        return {"low": None, "high": None, "label": "价格缺失"}
    low = price * Decimal("0.99")
    high = price * Decimal("1.01")
    return {
        "low": _decimal_to_number(low),
        "high": _decimal_to_number(high),
        "label": f"{low:.2f} - {high:.2f}",
    }


def _execution_hint(side: str) -> str:
    return {
        "BUY": "按价格区间分批买入，成交后手工记录到账户。",
        "ADD": "仅补足目标仓位，不追高突破价格上沿。",
        "REDUCE": "优先卖出超配部分，保留目标仓位。",
        "EXIT": "按风控优先级处理，可分批清仓并记录理由。",
        "HOLD": "无需下单，继续跟踪失效条件。",
        "WATCH": "加入观察，不形成订单。",
    }.get(side, "人工复核后处理。")


def _stable_order_intent_id(account_id: str, asset_code: str, side: str, source_id: str) -> str:
    raw = f"{account_id}|{asset_code}|{side}|{source_id}".encode()
    return f"oi_{hashlib.sha256(raw).hexdigest()[:16]}"


def _normalize_risk_policy_context(policy: dict[str, Any], *, unavailable: bool) -> dict[str, Any]:
    payload = dict(policy or {})
    parameters = dict(payload.get("parameters") or {})
    warnings = list(payload.get("warnings") or [])
    version_source = {
        "account_id": str(payload.get("account_id") or ""),
        "risk_profile": payload.get("risk_profile"),
        "template_key": payload.get("template_key"),
        "parameters": parameters,
        "sources": payload.get("sources") or {},
        "floor_applied": payload.get("floor_applied") or [],
        "exceptions_applied": payload.get("exceptions_applied") or [],
        "unavailable": unavailable,
    }
    version = (
        "riskcfg_"
        + hashlib.sha256(
            json.dumps(version_source, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]
    )
    return {
        "version": version,
        "account_id": str(payload.get("account_id") or ""),
        "risk_profile": payload.get("risk_profile") or "unknown",
        "template_key": payload.get("template_key"),
        "parameters": parameters,
        "sources": payload.get("sources") or {},
        "floor_applied": payload.get("floor_applied") or [],
        "exceptions_applied": payload.get("exceptions_applied") or [],
        "warnings": warnings,
        "unavailable": unavailable,
    }


def _normalize_data_health_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("status", "blocked")
    normalized.setdefault("asset_codes", [])
    normalized.setdefault("quotes", {})
    normalized.setdefault("market_thermometer", {})
    normalized.setdefault("blocked_reasons", [])
    normalized["must_not_use_for_decision"] = bool(
        normalized.get("must_not_use_for_decision")
        or normalized.get("status") in {"blocked", "failed"}
    )
    return normalized


def _data_health_warnings(data_health: dict[str, Any]) -> list[str]:
    return [f"data_health:{reason}" for reason in data_health.get("blocked_reasons") or []]


def _data_asof_for_asset(data_health: dict[str, Any], asset_code: str) -> dict[str, Any]:
    quote = dict((data_health.get("quotes") or {}).get(asset_code) or {})
    thermometer = dict(data_health.get("market_thermometer") or {})
    return {
        "asset_code": asset_code,
        "quote_snapshot_at": quote.get("snapshot_at"),
        "quote_freshness_status": quote.get("freshness_status") or quote.get("status"),
        "quote_source": quote.get("source"),
        "quote_must_not_use_for_decision": bool(quote.get("must_not_use_for_decision", False)),
        "market_thermometer_asof": thermometer.get("as_of_date")
        or thermometer.get("snapshot_date"),
        "market_thermometer_status": thermometer.get("status"),
    }


def _replace_intent(intent: AdvisorOrderIntent, **changes: Any) -> AdvisorOrderIntent:
    copied_changes: dict[str, Any] = {
        "price_band": dict(intent.price_band),
        "risk_notes": list(intent.risk_notes),
        "source_recommendation_ids": list(intent.source_recommendation_ids),
        "conflict_resolution": dict(intent.conflict_resolution),
        "risk_gate": dict(intent.risk_gate),
        "data_asof": dict(intent.data_asof),
        "decision_card": dict(intent.decision_card),
        "tracking": dict(intent.tracking),
        "confirmation": dict(intent.confirmation),
    }
    copied_changes.update(changes)
    return replace(intent, **copied_changes)


def _unique_asset_codes(values: list[str]) -> list[str]:
    return _dedupe_preserve_order([str(value or "").strip().upper() for value in values if value])


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _account_type_label(account_type: str) -> str:
    return {
        "real": "实盘账户",
        "simulated": "模拟盘账户",
        "paper": "模拟盘账户",
        "manual": "手工账户",
    }.get(account_type, account_type or "账户")


__all__ = [
    "_failed_execution_checks",
    "_build_signal_invalidation_check",
    "_recommendation_asset_code",
    "_normalize_recommendation_side",
    "_recommendation_id",
    "_recommendation_source_signal_ids",
    "_recommendation_source_candidate_ids",
    "_recommendation_reason",
    "_invalidation_rule",
    "_recommendation_price",
    "_recommended_target_weight",
    "_target_quantity",
    "_floor_quantity",
    "_price_band",
    "_execution_hint",
    "_stable_order_intent_id",
    "_normalize_risk_policy_context",
    "_normalize_data_health_payload",
    "_data_health_warnings",
    "_data_asof_for_asset",
    "_replace_intent",
    "_unique_asset_codes",
    "_dedupe_preserve_order",
    "_account_type_label",
]
