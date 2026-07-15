"""Allocation, exposure, confirmation, and execution-plan helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.asset_analysis.application.asset_name_service import resolve_asset_names_read_only
from apps.decision_rhythm.application.advisor_contracts import (
    ACTIONABLE_SIDES,
    BUY_SIDES,
    AdvisorAccessError,
    AdvisorHoldingSnapshot,
    AdvisorOrderIntent,
)
from apps.decision_rhythm.application.advisor_intents import (
    _dedupe_preserve_order,
    _recommendation_asset_code,
)
from apps.decision_rhythm.application.advisor_serialization import (
    _decimal_to_number,
    _normalize_percent,
    _optional_decimal,
    _serialize_time,
    _to_decimal,
)


def _parse_account_id(account_id: str) -> int:
    try:
        parsed = int(str(account_id).strip())
    except (TypeError, ValueError):
        raise AdvisorAccessError("account_id must be a valid account id", 400) from None
    if parsed <= 0:
        raise AdvisorAccessError("account_id must be a valid account id", 400)
    return parsed


def _merge_holdings(
    raw_holdings: list[dict[str, Any]],
    *,
    total_asset: Decimal,
) -> list[AdvisorHoldingSnapshot]:
    grouped: dict[str, dict[str, Any]] = {}
    for raw in raw_holdings:
        code = str(raw.get("asset_code") or raw.get("security_code") or "").strip().upper()
        if not code:
            continue
        quantity = _to_decimal(raw.get("quantity", raw.get("shares", 0)))
        market_value = _to_decimal(raw.get("market_value", 0))
        avg_cost = _to_decimal(raw.get("avg_cost", raw.get("cost", 0)))
        current_price = _optional_decimal(raw.get("current_price", raw.get("estimated_price")))
        pnl = _to_decimal(raw.get("unrealized_pnl", 0))
        pnl_pct = _normalize_percent(raw.get("unrealized_pnl_pct", 0))
        existing = grouped.setdefault(
            code,
            {
                "asset_code": code,
                "asset_name": raw.get("asset_name") or code,
                "asset_class": raw.get("asset_class") or raw.get("asset_type") or "equity",
                "quantity": Decimal("0"),
                "market_value": Decimal("0"),
                "cost_value": Decimal("0"),
                "current_price": current_price,
                "unrealized_pnl": Decimal("0"),
                "unrealized_pnl_pct": pnl_pct,
                "data_sources": set(),
                "price_time": raw.get("price_time") or raw.get("updated_at") or "",
            },
        )
        existing["quantity"] += quantity
        existing["market_value"] += market_value
        existing["cost_value"] += avg_cost * quantity
        existing["unrealized_pnl"] += pnl
        existing["data_sources"].add(str(raw.get("data_source") or raw.get("source") or "unknown"))
        if current_price and current_price > 0:
            existing["current_price"] = current_price
        if not existing["price_time"]:
            existing["price_time"] = raw.get("price_time") or raw.get("updated_at") or ""

    holdings: list[AdvisorHoldingSnapshot] = []
    for item in grouped.values():
        quantity = item["quantity"]
        market_value = item["market_value"]
        avg_cost = item["cost_value"] / quantity if quantity else Decimal("0")
        current_weight = market_value / total_asset if total_asset > 0 else Decimal("0")
        holdings.append(
            AdvisorHoldingSnapshot(
                asset_code=item["asset_code"],
                asset_name=str(item["asset_name"] or item["asset_code"]),
                asset_class=str(item["asset_class"] or "equity"),
                quantity=quantity,
                market_value=market_value,
                current_weight=current_weight,
                avg_cost=avg_cost,
                current_price=item["current_price"],
                unrealized_pnl=item["unrealized_pnl"],
                unrealized_pnl_pct=item["unrealized_pnl_pct"],
                data_source="unified",
                price_time=_serialize_time(item["price_time"]),
            )
        )
    return holdings


def _build_allocation_payload(
    holdings: list[AdvisorHoldingSnapshot],
    *,
    total_asset: Decimal,
) -> list[dict[str, Any]]:
    by_class: dict[str, Decimal] = {}
    for holding in holdings:
        by_class[holding.asset_class] = (
            by_class.get(holding.asset_class, Decimal("0")) + holding.market_value
        )
    if not by_class:
        by_class["equity"] = Decimal("0")
    payload: list[dict[str, Any]] = []
    for asset_class, current_amount in sorted(by_class.items()):
        target_weight = Decimal("0.60") if asset_class == "equity" else Decimal("0.10")
        current_weight = current_amount / total_asset if total_asset > 0 else Decimal("0")
        payload.append(
            {
                "asset_class": asset_class,
                "target_weight": _decimal_to_number(target_weight),
                "current_weight": _decimal_to_number(current_weight),
                "deviation_amount": _decimal_to_number(
                    (target_weight - current_weight) * total_asset
                ),
            }
        )
    return payload


def _build_exposure_summary(
    *,
    holdings: list[AdvisorHoldingSnapshot],
    order_intents: list[AdvisorOrderIntent],
    exposure_map: dict[str, dict[str, Any]],
    recommendations: list[Any],
    total_asset: Decimal,
    policy_context: dict[str, Any],
) -> dict[str, Any]:
    limits = _policy_exposure_limits(policy_context)
    strategy_by_asset = _strategy_by_asset(holdings=holdings, recommendations=recommendations)
    rows: dict[str, dict[str, dict[str, Any]]] = {
        "sector": {},
        "industry": {},
        "strategy": {},
    }
    missing_assets: list[str] = []

    def add_amount(
        *,
        dimension: str,
        name: str,
        asset_code: str,
        current_delta: Decimal,
        projected_delta: Decimal,
    ) -> None:
        bucket = rows[dimension].setdefault(
            name,
            {
                "name": name,
                "current_amount": Decimal("0"),
                "projected_amount": Decimal("0"),
                "asset_codes": [],
            },
        )
        bucket["current_amount"] += current_delta
        bucket["projected_amount"] += projected_delta
        bucket["asset_codes"] = _dedupe_preserve_order([*bucket["asset_codes"], asset_code])

    for holding in holdings:
        labels = _exposure_labels_for_asset(
            holding.asset_code,
            exposure_map=exposure_map,
            strategy_by_asset=strategy_by_asset,
            fallback_strategy=holding.asset_class,
        )
        if labels["missing"]:
            missing_assets.append(holding.asset_code)
        for dimension in ("sector", "industry", "strategy"):
            add_amount(
                dimension=dimension,
                name=labels[dimension],
                asset_code=holding.asset_code,
                current_delta=holding.market_value,
                projected_delta=holding.market_value,
            )

    for intent in order_intents:
        if intent.blocking_status != "OK" or intent.side not in ACTIONABLE_SIDES:
            continue
        direction = Decimal("1") if intent.side in BUY_SIDES else Decimal("-1")
        delta = direction * intent.estimated_amount
        labels = _exposure_labels_for_asset(
            intent.asset_code,
            exposure_map=exposure_map,
            strategy_by_asset=strategy_by_asset,
            fallback_strategy="unknown",
        )
        if labels["missing"]:
            missing_assets.append(intent.asset_code)
        for dimension in ("sector", "industry", "strategy"):
            add_amount(
                dimension=dimension,
                name=labels[dimension],
                asset_code=intent.asset_code,
                current_delta=Decimal("0"),
                projected_delta=delta,
            )

    payload: dict[str, Any] = {
        "total_asset": _decimal_to_number(total_asset),
        "limits": {
            dimension: _decimal_to_number(limit)
            for dimension, limit in limits.items()
            if limit is not None
        },
        "by_sector": [],
        "by_industry": [],
        "by_strategy": [],
        "alerts": [],
        "missing_exposure_assets": _dedupe_preserve_order(missing_assets),
    }

    for dimension, groups in rows.items():
        limit = limits[dimension]
        output_key = f"by_{dimension}"
        for name, item in sorted(groups.items()):
            current_amount = max(item["current_amount"], Decimal("0"))
            projected_amount = max(item["projected_amount"], Decimal("0"))
            current_weight = current_amount / total_asset if total_asset > 0 else Decimal("0")
            projected_weight = projected_amount / total_asset if total_asset > 0 else Decimal("0")
            status = "UNCONFIGURED"
            if limit is not None:
                status = "BREACH" if projected_weight > limit else "OK"
            row = {
                "name": name,
                "current_amount": _decimal_to_number(current_amount),
                "current_weight": _decimal_to_number(current_weight),
                "projected_amount": _decimal_to_number(projected_amount),
                "projected_weight": _decimal_to_number(projected_weight),
                "limit": _decimal_to_number(limit),
                "status": status,
                "asset_codes": list(item["asset_codes"]),
            }
            payload[output_key].append(row)
            if status == "BREACH":
                payload["alerts"].extend(
                    _exposure_alerts_for_group(
                        dimension=dimension,
                        group=row,
                        order_intents=order_intents,
                    )
                )
    return payload


def _exposure_alerts_for_group(
    *,
    dimension: str,
    group: dict[str, Any],
    order_intents: list[AdvisorOrderIntent],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    buy_codes = {
        intent.asset_code
        for intent in order_intents
        if intent.side in BUY_SIDES and intent.blocking_status == "OK"
    }
    for asset_code in group["asset_codes"]:
        if asset_code not in buy_codes:
            continue
        message = (
            f"{dimension} 暴露 {group['name']} 预计权重 "
            f"{group['projected_weight']:.2%} 超过上限 {group['limit']:.2%}。"
        )
        alerts.append(
            {
                "asset_code": asset_code,
                "dimension": dimension,
                "name": group["name"],
                "projected_weight": group["projected_weight"],
                "limit": group["limit"],
                "message": message,
            }
        )
    return alerts


def _exposure_guard_for_intent(
    intent: AdvisorOrderIntent,
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    if intent.blocking_status != "OK" or intent.side not in BUY_SIDES:
        return {"status": "SKIPPED", "code": "not_buy_or_already_blocked", "messages": []}
    if not alerts:
        return {"status": "OK", "code": "exposure_guard_passed", "messages": []}
    return {
        "status": "BLOCKED",
        "code": "exposure_limit_exceeded",
        "messages": [str(item.get("message") or "") for item in alerts if item.get("message")],
        "alerts": alerts,
    }


def _policy_exposure_limits(policy_context: dict[str, Any]) -> dict[str, Decimal | None]:
    parameters = dict(policy_context.get("parameters") or {})
    return {
        "sector": _policy_limit_weight(parameters.get("max_sector_position_pct")),
        "industry": _policy_limit_weight(parameters.get("max_industry_position_pct")),
        "strategy": _policy_limit_weight(parameters.get("max_strategy_position_pct")),
    }


def _policy_limit_weight(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    limit = _to_decimal(value)
    if limit <= 0:
        return None
    if limit > Decimal("1"):
        limit = limit / Decimal("100")
    return limit


def _normalize_exposure_map(raw: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for asset_code, payload in (raw or {}).items():
        code = str(asset_code or "").strip().upper()
        if not code:
            continue
        item = dict(payload or {})
        normalized[code] = {
            "sector": str(item.get("sector") or "").strip(),
            "industry": str(item.get("industry") or "").strip(),
            "asset_type": str(item.get("asset_type") or "").strip(),
            "strategy": str(
                item.get("strategy")
                or item.get("strategy_bucket")
                or item.get("strategy_key")
                or ""
            ).strip(),
            "lookup_error": str(item.get("lookup_error") or "").strip(),
        }
    return normalized


def _strategy_by_asset(
    *,
    holdings: list[AdvisorHoldingSnapshot],
    recommendations: list[Any],
) -> dict[str, str]:
    strategies = {
        holding.asset_code: holding.asset_class
        for holding in holdings
        if holding.asset_code and holding.asset_class
    }
    for recommendation in recommendations:
        asset_code = _recommendation_asset_code(recommendation)
        strategy = _recommendation_strategy(recommendation)
        if asset_code and strategy:
            strategies[asset_code] = strategy
    return strategies


def _recommendation_strategy(recommendation: Any | None) -> str:
    if recommendation is None:
        return ""
    for attr in (
        "strategy_bucket",
        "strategy_key",
        "strategy",
        "source_strategy",
        "source_type",
        "source_module",
    ):
        value = str(getattr(recommendation, attr, "") or "").strip()
        if value:
            return value
    return ""


def _exposure_labels_for_asset(
    asset_code: str,
    *,
    exposure_map: dict[str, dict[str, Any]],
    strategy_by_asset: dict[str, str],
    fallback_strategy: str,
) -> dict[str, Any]:
    exposure = exposure_map.get(asset_code) or {}
    sector = str(exposure.get("sector") or "").strip() or "unknown"
    industry = str(exposure.get("industry") or "").strip() or "unknown"
    strategy = (
        str(exposure.get("strategy") or "").strip()
        or str(strategy_by_asset.get(asset_code) or "").strip()
        or fallback_strategy
        or "unknown"
    )
    return {
        "sector": sector,
        "industry": industry,
        "strategy": strategy,
        "missing": sector == "unknown" or industry == "unknown",
    }


def _build_order_summary(order_intents: list[AdvisorOrderIntent]) -> dict[str, Any]:
    counts = dict.fromkeys(["BUY", "ADD", "REDUCE", "EXIT", "HOLD", "WATCH"], 0)
    actionable_count = 0
    blocked_count = 0
    for intent in order_intents:
        counts[intent.side] = counts.get(intent.side, 0) + 1
        if intent.side in ACTIONABLE_SIDES:
            actionable_count += 1
        if intent.blocking_status != "OK":
            blocked_count += 1
    return {
        "total": len(order_intents),
        "actionable": actionable_count,
        "blocked": blocked_count,
        "buy": counts["BUY"],
        "add": counts["ADD"],
        "reduce": counts["REDUCE"],
        "exit": counts["EXIT"],
        "hold": counts["HOLD"],
        "watch": counts["WATCH"],
    }


def _build_advisor_execution_plan(
    *,
    account: dict[str, Any],
    order_payloads: list[dict[str, Any]],
    verdict: str,
    data_health: dict[str, Any],
) -> dict[str, Any]:
    executable_orders = [
        order
        for order in order_payloads
        if order.get("side") in ACTIONABLE_SIDES and order.get("blocking_status") == "OK"
    ]
    confirmation_required = any(
        bool((order.get("confirmation") or {}).get("required")) for order in executable_orders
    )
    account_type = str(account.get("account_type") or "").lower()
    execution_mode = "real_confirm_only" if account_type == "real" else "semi_auto_plan"
    if not executable_orders:
        execution_mode = "no_executable_orders"
    return {
        "status": "READY_FOR_CONFIRMATION" if executable_orders else "NO_EXECUTABLE_ORDERS",
        "execution_mode": execution_mode,
        "broker_execution_enabled": False,
        "requires_human_confirmation": confirmation_required,
        "confirmation_status": ("PENDING" if confirmation_required else "NOT_REQUIRED"),
        "real_account_guard": {
            "account_type": account_type or "unknown",
            "real_broker_order_allowed": False,
            "message": "真实账户只生成交易计划、确认和记录，不自动下单。",
        },
        "data_health_status": data_health.get("status"),
        "orders_count": len(executable_orders),
        "orders": [
            {
                "order_intent_id": order.get("order_intent_id"),
                "asset_code": order.get("asset_code"),
                "asset_name": order.get("asset_name"),
                "side": order.get("side"),
                "suggested_quantity": abs(_to_decimal(order.get("delta_quantity"))),
                "suggested_amount": order.get("estimated_amount"),
                "price_band": order.get("price_band") or {},
                "priority": order.get("priority"),
                "pre_trade_checks": {
                    "risk_gate_status": order.get("risk_gate_status"),
                    "blocking_status": order.get("blocking_status"),
                    "risk_gate": order.get("risk_gate") or {},
                    "data_asof": order.get("data_asof") or {},
                },
                "valid_until": (order.get("decision_card") or {}).get("valid_until"),
                "confirmation": order.get("confirmation") or {},
            }
            for order in executable_orders
        ],
    }


def _confirmation_payload_for_intent(
    *,
    intent: AdvisorOrderIntent,
    account: dict[str, Any],
    order_intents: list[AdvisorOrderIntent],
    data_health: dict[str, Any],
    policy_context: dict[str, Any],
) -> dict[str, Any]:
    if intent.side not in ACTIONABLE_SIDES or intent.blocking_status != "OK":
        return {
            "required": False,
            "status": "NOT_APPLICABLE",
            "reasons": [],
            "confirmable": False,
            "confirmation_token": None,
        }

    parameters = dict(policy_context.get("parameters") or {})
    threshold = _confirmation_amount_threshold(parameters)
    reasons: list[dict[str, Any]] = []
    if threshold is not None and intent.estimated_amount > threshold:
        reasons.append(
            {
                "code": "large_order_amount",
                "message": "单笔金额超过人工确认阈值。",
                "threshold": _decimal_to_number(threshold),
                "actual": _decimal_to_number(intent.estimated_amount),
            }
        )
    if intent.side in {"REDUCE", "EXIT"}:
        sell_reason = _sell_confirmation_reason(intent)
        if sell_reason:
            reasons.append(sell_reason)
    if intent.side == "ADD":
        reasons.append(
            {
                "code": "consecutive_add",
                "message": "连续加仓或对已持仓资产加仓，需要人工确认。",
            }
        )
    if _actionable_orders_count(order_intents) > _daily_trade_confirmation_threshold(parameters):
        reasons.append(
            {
                "code": "multiple_daily_trades",
                "message": "当天建议执行单数较多，需要人工确认。",
                "actual": _actionable_orders_count(order_intents),
            }
        )
    if _data_health_requires_confirmation(data_health):
        reasons.append(
            {
                "code": "data_health_warning",
                "message": "存在数据健康 warning/blocking 信息，执行前需要人工确认。",
                "status": data_health.get("status"),
            }
        )
    if _is_high_volatility_asset(intent, parameters):
        reasons.append(
            {
                "code": "high_volatility_asset",
                "message": "高波动资产买入或加仓需要人工确认。",
            }
        )
    if str(account.get("account_type") or "").lower() == "real":
        reasons.append(
            {
                "code": "real_account_manual_confirm",
                "message": "真实账户只允许建议、确认和记录，不允许自动下单。",
            }
        )

    reasons = _dedupe_confirmation_reasons(reasons)
    return {
        "required": bool(reasons),
        "status": "PENDING" if reasons else "NOT_REQUIRED",
        "reasons": reasons,
        "confirmable": True,
        "confirmation_token": None,
        "approval_entry": {
            "kind": "advisor_order_intent",
            "order_intent_id": intent.order_intent_id,
            "source_recommendation_ids": list(intent.source_recommendation_ids),
        },
    }


def _confirmation_amount_threshold(parameters: dict[str, Any]) -> Decimal | None:
    for key in (
        "advisor_confirmation_amount_threshold",
        "confirmation_amount_threshold",
        "large_order_amount_threshold",
    ):
        value = parameters.get(key)
        if value not in (None, ""):
            threshold = _to_decimal(value)
            return threshold if threshold > 0 else None
    return Decimal("50000")


def _daily_trade_confirmation_threshold(parameters: dict[str, Any]) -> int:
    value = _to_decimal(parameters.get("daily_trade_confirmation_threshold", 3))
    return max(1, int(value))


def _actionable_orders_count(order_intents: list[AdvisorOrderIntent]) -> int:
    return len(
        [
            intent
            for intent in order_intents
            if intent.side in ACTIONABLE_SIDES and intent.blocking_status == "OK"
        ]
    )


def _sell_confirmation_reason(intent: AdvisorOrderIntent) -> dict[str, Any] | None:
    if "浮亏超过 10%" in intent.reason:
        return {
            "code": "large_loss_exit",
            "message": "卖出亏损持仓，需要人工确认。",
        }
    if intent.side == "EXIT" and intent.current_weight >= Decimal("0.10"):
        return {
            "code": "large_position_exit",
            "message": "清仓较大持仓，需要人工确认。",
        }
    return None


def _data_health_requires_confirmation(data_health: dict[str, Any]) -> bool:
    if data_health.get("status") not in {None, "", "ok"}:
        return True
    if data_health.get("blocked_reasons"):
        return True
    quotes = data_health.get("quotes") or {}
    for quote in quotes.values():
        if not isinstance(quote, dict):
            continue
        freshness = str(quote.get("freshness_status") or quote.get("status") or "").lower()
        if freshness and freshness not in {"ok", "fresh"}:
            return True
    return False


def _is_high_volatility_asset(intent: AdvisorOrderIntent, parameters: dict[str, Any]) -> bool:
    raw_assets = parameters.get("high_volatility_assets", []) or []
    if isinstance(raw_assets, str):
        raw_assets = [item.strip() for item in raw_assets.split(",")]
    configured = {str(item).strip().upper() for item in raw_assets}
    if intent.asset_code in configured:
        return True
    risk_notes = " ".join(intent.risk_notes).lower()
    return "高波动" in risk_notes or "volatility" in risk_notes


def _dedupe_confirmation_reasons(reasons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for reason in reasons:
        code = str(reason.get("code") or "")
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(reason)
    return result


def _build_risk_summary(
    holdings: list[AdvisorHoldingSnapshot],
    blockers: list[dict[str, Any]],
    warnings: list[str],
    *,
    exposure_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    top_weight = max((holding.current_weight for holding in holdings), default=Decimal("0"))
    over_weight = [
        holding.asset_code for holding in holdings if holding.current_weight > Decimal("0.25")
    ]
    return {
        "top_position_weight": _decimal_to_number(top_weight),
        "overweight_positions": over_weight,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "exposure_alerts": list((exposure_summary or {}).get("alerts") or []),
    }


def _build_next_actions(*, verdict: str, has_orders: bool) -> list[dict[str, str]]:
    actions = [
        {"key": "refresh_recommendations", "label": "刷新推荐", "hint": "重新生成账户推荐输入。"},
        {
            "key": "view_conflicts",
            "label": "查看冲突/阻断",
            "hint": "核对 Beta Gate、冷却期、配额和价格缺失。",
        },
    ]
    if has_orders and verdict in {"ACT", "REVIEW"}:
        actions.extend(
            [
                {
                    "key": "generate_plan",
                    "label": "生成 Workspace 计划",
                    "hint": "把已采纳建议转入计划预览。",
                },
                {
                    "key": "copy_manual_list",
                    "label": "复制手工执行清单",
                    "hint": "用于人工下单或记录成交。",
                },
            ]
        )
    actions.append(
        {"key": "record_manual_fill", "label": "手工记录成交", "hint": "执行后在账户中补录成交。"}
    )
    return actions


def _resolve_verdict(
    *,
    order_intents: list[AdvisorOrderIntent],
    blockers: list[dict[str, Any]],
    warnings: list[str],
    data_health_blocked: bool = False,
    has_recommendation_conflicts: bool = False,
) -> str:
    actionable = [item for item in order_intents if item.side in ACTIONABLE_SIDES]
    executable = [item for item in actionable if item.blocking_status == "OK"]
    if actionable and not executable:
        return "BLOCKED"
    if data_health_blocked and executable:
        return "REVIEW"
    if has_recommendation_conflicts and executable:
        return "REVIEW"
    if any(item.risk_gate_status == "REVIEW" for item in executable):
        return "REVIEW"
    if executable:
        return "ACT"
    if blockers or warnings:
        return "REVIEW"
    return "WAIT"


def _resolve_missing_names(
    holdings: list[AdvisorHoldingSnapshot], recommendations: list[Any]
) -> dict[str, str]:
    names = {holding.asset_code: holding.asset_name for holding in holdings if holding.asset_name}
    codes = [_recommendation_asset_code(item) for item in recommendations]
    missing = [code for code in codes if code and code not in names]
    if missing:
        names.update(resolve_asset_names_read_only(missing))
    return names


__all__ = [
    "_parse_account_id",
    "_merge_holdings",
    "_build_allocation_payload",
    "_build_exposure_summary",
    "_exposure_alerts_for_group",
    "_exposure_guard_for_intent",
    "_policy_exposure_limits",
    "_policy_limit_weight",
    "_normalize_exposure_map",
    "_strategy_by_asset",
    "_recommendation_strategy",
    "_exposure_labels_for_asset",
    "_build_order_summary",
    "_build_advisor_execution_plan",
    "_confirmation_payload_for_intent",
    "_confirmation_amount_threshold",
    "_daily_trade_confirmation_threshold",
    "_actionable_orders_count",
    "_sell_confirmation_reason",
    "_data_health_requires_confirmation",
    "_is_high_volatility_asset",
    "_dedupe_confirmation_reasons",
    "_build_risk_summary",
    "_build_next_actions",
    "_resolve_verdict",
    "_resolve_missing_names",
]
