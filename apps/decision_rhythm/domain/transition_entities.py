"""Portfolio transition plan, order, and decision queue entities."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any
from uuid import uuid4

from .recommendation_entities import RecommendationStatus, UnifiedRecommendation
from .valuation_entities import RecommendationSide


class TransitionPlanStatus(Enum):
    """交易计划状态枚举。"""

    DRAFT = "DRAFT"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TransitionOrder:
    """账户级调仓指令。"""

    security_code: str
    action: str
    current_qty: int
    target_qty: int
    delta_qty: int
    current_weight: float
    target_weight: float
    price_band_low: Decimal
    price_band_high: Decimal
    max_capital: Decimal
    stop_loss_price: Decimal | None
    invalidation_rule: dict[str, Any]
    execution_price: Decimal | None = None
    price_source: str = ""
    take_profit_price: Decimal | None = None
    take_profit_source: str = ""
    stop_loss_source: str = ""
    thesis: str = ""
    risk_summary: str = ""
    reward_risk: dict[str, Any] = field(default_factory=dict)
    data_asof: str = ""
    invalidation_description: str = ""
    requires_user_confirmation: bool = False
    review_by: str | None = None
    time_horizon: str = "swing"
    source_recommendation_id: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def is_hold(self) -> bool:
        return self.action == "HOLD"

    @property
    def is_ready_for_approval(self) -> bool:
        if self.is_hold:
            return False
        if self.stop_loss_price in [None, Decimal("0"), "0", 0]:
            return False
        if not self.invalidation_rule:
            return False
        if self.invalidation_rule.get("requires_user_confirmation"):
            return False
        return bool(self.invalidation_rule.get("conditions"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "action": self.action,
            "current_qty": self.current_qty,
            "target_qty": self.target_qty,
            "delta_qty": self.delta_qty,
            "current_weight": self.current_weight,
            "target_weight": self.target_weight,
            "price_band_low": str(self.price_band_low),
            "price_band_high": str(self.price_band_high),
            "execution_price": (
                str(self.execution_price) if self.execution_price is not None else None
            ),
            "price_source": self.price_source,
            "take_profit_price": (
                str(self.take_profit_price) if self.take_profit_price is not None else None
            ),
            "take_profit_source": self.take_profit_source,
            "max_capital": str(self.max_capital),
            "stop_loss_price": (
                str(self.stop_loss_price) if self.stop_loss_price is not None else None
            ),
            "stop_loss_source": self.stop_loss_source,
            "thesis": self.thesis,
            "risk_summary": self.risk_summary,
            "reward_risk": self.reward_risk,
            "data_asof": self.data_asof,
            "invalidation_rule": self.invalidation_rule,
            "invalidation_description": self.invalidation_description,
            "requires_user_confirmation": self.requires_user_confirmation,
            "review_by": self.review_by,
            "time_horizon": self.time_horizon,
            "source_recommendation_id": self.source_recommendation_id,
            "notes": self.notes,
            "is_ready_for_approval": self.is_ready_for_approval,
        }


@dataclass(frozen=True)
class PortfolioTransitionPlan:
    """账户级调仓计划。"""

    plan_id: str
    account_id: str
    as_of: datetime
    source_recommendation_ids: list[str]
    current_positions_snapshot: list[dict[str, Any]]
    target_positions_snapshot: list[dict[str, Any]]
    orders: list[TransitionOrder]
    risk_contract: dict[str, Any]
    summary: dict[str, Any]
    status: TransitionPlanStatus = TransitionPlanStatus.DRAFT
    approval_request_id: str | None = None

    @property
    def blocking_issues(self) -> list[str]:
        issues: list[str] = []
        actionable_orders = [order for order in self.orders if not order.is_hold]
        if not actionable_orders:
            return ["当前计划没有可执行订单"]
        for order in actionable_orders:
            if order.stop_loss_price in [None, Decimal("0"), "0", 0]:
                issues.append(f"{order.security_code}: 缺少止损价")
            if not order.invalidation_rule or order.invalidation_rule.get(
                "requires_user_confirmation"
            ):
                issues.append(f"{order.security_code}: 缺少完整证伪条件")
            elif not order.invalidation_rule.get("conditions"):
                issues.append(f"{order.security_code}: 证伪条件为空")
        return issues

    @property
    def can_enter_approval(self) -> bool:
        return not self.blocking_issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "account_id": self.account_id,
            "as_of": self.as_of.isoformat(),
            "source_recommendation_ids": self.source_recommendation_ids,
            "current_positions": self.current_positions_snapshot,
            "target_positions": self.target_positions_snapshot,
            "orders": [order.to_dict() for order in self.orders],
            "risk_contract": self.risk_contract,
            "summary": self.summary,
            "status": self.status.value,
            "approval_request_id": self.approval_request_id,
            "can_enter_approval": self.can_enter_approval,
            "blocking_issues": self.blocking_issues,
        }


@dataclass(frozen=True)
class TodayDecisionQueueItem:
    """One actionable item in the daily decision queue."""

    item_id: str
    type: str
    title: str
    status: str
    priority: int
    account_id: str
    security_code: str
    source_id: str
    next_action: str
    target_screen: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        """Return an API-safe queue item payload."""

        return {
            "item_id": self.item_id,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "account_id": self.account_id,
            "security_code": self.security_code,
            "source_id": self.source_id,
            "next_action": self.next_action,
            "target_screen": self.target_screen,
            "created_at": self.created_at.isoformat(),
        }


def sort_today_decision_queue_items(
    items: list[TodayDecisionQueueItem],
) -> list[TodayDecisionQueueItem]:
    """Sort daily queue items by priority, then newest first."""

    return sorted(
        items,
        key=lambda item: (
            item.priority,
            -item.created_at.timestamp(),
            item.item_id,
        ),
    )


def _build_default_invalidation_rule() -> dict[str, Any]:
    return {
        "logic": "AND",
        "conditions": [],
        "requires_user_confirmation": True,
    }


def _resolve_invalidation_payload(
    signal_ids: list[str],
    signal_payloads: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, bool]:
    payloads = signal_payloads or {}
    for signal_id in signal_ids:
        payload = payloads.get(str(signal_id)) or {}
        rule = payload.get("invalidation_rule_json")
        if rule:
            return (
                rule,
                str(
                    payload.get("invalidation_description")
                    or payload.get("invalidation_logic")
                    or ""
                ),
                False,
            )
    return _build_default_invalidation_rule(), "待补充证伪条件", True


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in [None, ""]:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def _midpoint_price(low: Decimal, high: Decimal) -> Decimal | None:
    if low > 0 and high > 0:
        return (low + high) / Decimal("2")
    if low > 0:
        return low
    if high > 0:
        return high
    return None


def _resolve_transition_execution_price(
    action: str,
    current_position: dict[str, Any],
    price_band_low: Decimal,
    price_band_high: Decimal,
) -> tuple[Decimal | None, str]:
    if action == "HOLD":
        return None, ""
    current_price = _decimal_or_none(current_position.get("current_price"))
    if action in ["REDUCE", "EXIT"] and current_price is not None:
        return current_price, "current_position_price"
    band_midpoint = _midpoint_price(price_band_low, price_band_high)
    if band_midpoint is not None:
        source = "entry_price_band_midpoint" if action == "BUY" else "target_price_band_midpoint"
        return band_midpoint, source
    if current_price is not None:
        return current_price, "current_position_price"
    return None, ""


def _resolve_transition_stop_loss(
    action: str,
    recommendation_stop_loss: Any,
    execution_price: Decimal | None,
) -> tuple[Decimal | None, str, str | None]:
    stop_loss_price = _decimal_or_none(recommendation_stop_loss)
    if stop_loss_price is not None:
        return stop_loss_price, "recommendation_stop_loss", None
    if action != "HOLD" and execution_price is not None and execution_price > 0:
        auto_stop = (execution_price * Decimal("0.90")).quantize(Decimal("0.0001"))
        return auto_stop, "auto_90pct_execution_price", "auto_stop_loss_from_execution_price"
    if action != "HOLD":
        return None, "", "missing_stop_loss"
    return None, "", None


def _resolve_transition_take_profit(
    action: str,
    target_price_low: Decimal,
    target_price_high: Decimal,
    execution_price: Decimal | None,
) -> tuple[Decimal | None, str]:
    if action == "HOLD":
        return None, ""
    target_midpoint = _midpoint_price(target_price_low, target_price_high)
    if target_midpoint is not None:
        return target_midpoint, "target_price_band_midpoint"
    if execution_price is not None and execution_price > 0:
        return (execution_price * Decimal("1.15")).quantize(Decimal("0.0001")), (
            "auto_115pct_execution_price"
        )
    return None, ""


def _pct_value(numerator: Decimal, denominator: Decimal) -> str:
    return str(((numerator / denominator) * Decimal("100")).quantize(Decimal("0.01")))


def calculate_transition_reward_risk(
    execution_price: Decimal | None,
    take_profit_price: Decimal | None,
    stop_loss_price: Decimal | None,
) -> dict[str, Any]:
    """Return the normalized reward-risk contract for a transition order."""
    payload: dict[str, Any] = {
        "entry_price": str(execution_price) if execution_price is not None else None,
        "take_profit_price": str(take_profit_price) if take_profit_price is not None else None,
        "stop_loss_price": str(stop_loss_price) if stop_loss_price is not None else None,
        "upside_pct": None,
        "downside_pct": None,
        "ratio": None,
    }
    if not execution_price or not take_profit_price or not stop_loss_price or execution_price <= 0:
        return payload
    upside = take_profit_price - execution_price
    downside = execution_price - stop_loss_price
    if downside <= 0:
        return payload
    payload["upside_pct"] = _pct_value(upside, execution_price)
    payload["downside_pct"] = _pct_value(downside, execution_price)
    payload["ratio"] = str((upside / downside).quantize(Decimal("0.01")))
    return payload


def _resolve_transition_thesis(recommendation: "UnifiedRecommendation", action: str) -> str:
    rationale = str(getattr(recommendation, "human_rationale", "") or "").strip()
    if rationale:
        return rationale
    reason_codes = list(getattr(recommendation, "reason_codes", []) or [])
    if reason_codes:
        return ", ".join(str(code) for code in reason_codes)
    security_code = str(getattr(recommendation, "security_code", "") or "").upper()
    action_label = {"BUY": "买入", "SELL": "卖出", "EXIT": "清仓", "REDUCE": "减仓"}.get(
        action,
        action,
    )
    return f"{action_label} {security_code}：推荐理由待补充"


def create_portfolio_transition_plan(
    account_id: str,
    recommendations: list["UnifiedRecommendation"],
    current_positions: list[dict[str, Any]],
    signal_payloads: dict[str, dict[str, Any]] | None = None,
    risk_contract: dict[str, Any] | None = None,
    as_of: datetime | None = None,
) -> PortfolioTransitionPlan:
    """
    根据当前账户持仓和推荐生成账户级调仓计划。
    """

    as_of_time = as_of or datetime.now(UTC)
    signal_payload_map = signal_payloads or {}
    current_position_map = {
        str(position.get("asset_code") or "").upper(): position
        for position in current_positions
        if position.get("asset_code")
    }
    total_market_value = sum(
        Decimal(str(position.get("market_value") or "0")) for position in current_positions
    )
    orders: list[TransitionOrder] = []
    filtered_out: list[dict[str, str]] = []
    target_positions: list[dict[str, Any]] = []

    for recommendation in recommendations:
        if getattr(recommendation, "status", None) == RecommendationStatus.CONFLICT:
            filtered_out.append(
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "security_code": recommendation.security_code,
                    "reason": "conflict",
                }
            )
            continue

        security_code = str(recommendation.security_code or "").upper()
        current_position = current_position_map.get(security_code, {})
        current_qty = int(current_position.get("quantity") or 0)
        current_market_value = Decimal(str(current_position.get("market_value") or "0"))
        current_weight = 0.0
        if total_market_value > 0:
            current_weight = float((current_market_value / total_market_value) * Decimal("100"))

        desired_qty = int(max(getattr(recommendation, "suggested_quantity", 0) or 0, 0))
        action = "HOLD"
        target_qty = current_qty
        target_weight = current_weight
        notes: list[str] = []
        if recommendation.side == RecommendationSide.BUY.value:
            target_qty = max(current_qty, desired_qty)
            if target_qty > current_qty:
                action = "BUY"
            target_weight = float(getattr(recommendation, "position_pct", 0.0) or 0.0)
        elif recommendation.side == RecommendationSide.SELL.value:
            if current_qty <= 0:
                filtered_out.append(
                    {
                        "recommendation_id": recommendation.recommendation_id,
                        "security_code": recommendation.security_code,
                        "reason": "no_position_to_sell",
                    }
                )
                continue
            reduction_qty = desired_qty if desired_qty > 0 else current_qty
            reduction_qty = min(current_qty, reduction_qty)
            target_qty = max(current_qty - reduction_qty, 0)
            action = "EXIT" if target_qty == 0 else "REDUCE"
            if current_qty > 0:
                target_weight = round(current_weight * (target_qty / current_qty), 2)
        else:
            if current_qty > 0 and desired_qty > 0 and desired_qty < current_qty:
                target_qty = desired_qty
                action = "REDUCE"
                target_weight = round(current_weight * (target_qty / current_qty), 2)
                notes.append("reduce_from_hold_target")
            else:
                target_qty = current_qty
                action = "HOLD"

        delta_qty = target_qty - current_qty
        invalidation_rule, invalidation_description, requires_confirmation = (
            _resolve_invalidation_payload(
                list(getattr(recommendation, "source_signal_ids", []) or []),
                signal_payload_map,
            )
        )
        entry_price_low = Decimal(
            str(getattr(recommendation, "entry_price_low", Decimal("0")) or "0")
        )
        entry_price_high = Decimal(
            str(getattr(recommendation, "entry_price_high", Decimal("0")) or "0")
        )
        target_price_low = Decimal(
            str(getattr(recommendation, "target_price_low", Decimal("0")) or "0")
        )
        target_price_high = Decimal(
            str(getattr(recommendation, "target_price_high", Decimal("0")) or "0")
        )
        price_band_low = entry_price_low if action == "BUY" else target_price_low
        price_band_high = entry_price_high if action == "BUY" else target_price_high
        price_band_low = Decimal(str(price_band_low or "0"))
        price_band_high = Decimal(str(price_band_high or "0"))
        execution_price, price_source = _resolve_transition_execution_price(
            action,
            current_position,
            price_band_low,
            price_band_high,
        )
        stop_loss_price, stop_loss_source, stop_loss_note = _resolve_transition_stop_loss(
            action,
            getattr(recommendation, "stop_loss_price", None),
            execution_price,
        )
        take_profit_price, take_profit_source = _resolve_transition_take_profit(
            action,
            target_price_low,
            target_price_high,
            execution_price,
        )
        if stop_loss_note:
            notes.append(stop_loss_note)
        risk_summary = invalidation_description or "证伪条件待补充"
        order = TransitionOrder(
            security_code=security_code,
            action=action,
            current_qty=current_qty,
            target_qty=target_qty,
            delta_qty=delta_qty,
            current_weight=round(current_weight, 2),
            target_weight=round(target_weight, 2),
            price_band_low=price_band_low,
            price_band_high=price_band_high,
            max_capital=Decimal(str(getattr(recommendation, "max_capital", "0") or "0")),
            stop_loss_price=stop_loss_price,
            invalidation_rule=invalidation_rule,
            execution_price=execution_price,
            price_source=price_source,
            take_profit_price=take_profit_price,
            take_profit_source=take_profit_source,
            stop_loss_source=stop_loss_source,
            thesis=_resolve_transition_thesis(recommendation, action),
            risk_summary=risk_summary,
            reward_risk=calculate_transition_reward_risk(
                execution_price,
                take_profit_price,
                stop_loss_price,
            ),
            data_asof=getattr(recommendation, "updated_at", as_of_time).isoformat(),
            invalidation_description=invalidation_description,
            requires_user_confirmation=requires_confirmation,
            review_by=(as_of_time + timedelta(days=5)).date().isoformat(),
            source_recommendation_id=recommendation.recommendation_id,
            notes=notes,
        )
        orders.append(order)
        target_positions.append(
            {
                "security_code": security_code,
                "target_qty": target_qty,
                "target_weight": round(target_weight, 2),
                "action": action,
                "source_recommendation_id": recommendation.recommendation_id,
            }
        )

    default_risk_contract = {
        "max_single_position_pct": 20.0,
        "max_total_turnover_pct": 50.0,
        "cash_floor": 10.0,
        "portfolio_drawdown_guard": 12.0,
        "gate_snapshot": "decision_workspace_v2",
        "quota_snapshot": "weekly",
    }
    if risk_contract:
        default_risk_contract.update(risk_contract)

    summary = {
        "orders_count": len(orders),
        "buy_count": sum(1 for order in orders if order.action == "BUY"),
        "reduce_count": sum(1 for order in orders if order.action == "REDUCE"),
        "exit_count": sum(1 for order in orders if order.action == "EXIT"),
        "hold_count": sum(1 for order in orders if order.action == "HOLD"),
        "filtered_out": filtered_out,
    }

    plan = PortfolioTransitionPlan(
        plan_id=f"plan_{uuid4().hex[:12]}",
        account_id=account_id,
        as_of=as_of_time,
        source_recommendation_ids=[
            recommendation.recommendation_id for recommendation in recommendations
        ],
        current_positions_snapshot=current_positions,
        target_positions_snapshot=target_positions,
        orders=orders,
        risk_contract=default_risk_contract,
        summary=summary,
        status=TransitionPlanStatus.DRAFT,
    )

    if plan.can_enter_approval:
        return replace(plan, status=TransitionPlanStatus.READY_FOR_APPROVAL)
    return plan


__all__ = [
    "TransitionPlanStatus",
    "TransitionOrder",
    "PortfolioTransitionPlan",
    "TodayDecisionQueueItem",
    "sort_today_decision_queue_items",
    "_build_default_invalidation_rule",
    "_resolve_invalidation_payload",
    "_decimal_or_none",
    "_midpoint_price",
    "_resolve_transition_execution_price",
    "_resolve_transition_stop_loss",
    "_resolve_transition_take_profit",
    "_pct_value",
    "calculate_transition_reward_risk",
    "_resolve_transition_thesis",
    "create_portfolio_transition_plan",
]
