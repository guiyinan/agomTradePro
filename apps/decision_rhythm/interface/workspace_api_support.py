"""Shared support for decision rhythm workspace API views."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_provider.application.chat_completion import AIClientFactory, generate_chat_completion
from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.decision_rhythm.application.user_action_labels import build_user_action_label
from apps.regime.application.current_regime import resolve_current_regime

from ..application.dtos import (
    ConflictsListDTO,
    RecommendationsListDTO,
    RefreshRecommendationsRequestDTO,
)
from ..application.workspace_services import (
    build_plan_risk_checks as workspace_build_plan_risk_checks,
)
from ..application.workspace_services import (
    build_recommendation_risk_checks,
    create_legacy_approval,
    create_plan_approval,
    create_unified_approval,
    get_aggregated_workspace_payload,
    get_approval_request,
    get_legacy_recommendation,
    get_model_params_payload,
    get_related_candidate_ids,
    get_signal_payloads,
    get_transition_plan,
    get_unified_recommendation,
    get_valuation_repair_map,
    get_valuation_snapshot,
    has_pending_request,
    list_workspace_conflicts,
    list_workspace_recommendations,
    recalculate_valuation_snapshot,
    refresh_workspace_recommendations,
    save_transition_plan,
    serialize_transition_plan_payload,
    update_approval_request_status,
    update_model_param_payload,
    update_workspace_recommendation_action,
)
from ..application.workspace_services import (
    build_transition_plan_for_account as workspace_build_transition_plan_for_account,
)
from ..domain.entities import (
    ApprovalStatus,
    PortfolioTransitionPlan,
    TransitionOrder,
    TransitionPlanStatus,
    UserDecisionAction,
)
from ..domain.services import (
    ApprovalStatusStateMachine,
    ExecutionApprovalService,
)

logger = logging.getLogger(__name__)

def _decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default

def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def _regime_context() -> dict[str, Any]:
    try:
        current = resolve_current_regime()
        return {
            "current_regime": getattr(current, "dominant_regime", "UNKNOWN") or "UNKNOWN",
            "confidence": float(getattr(current, "confidence", 0.0) or 0.0),
            "source": getattr(current, "data_source", "V2_CALCULATION") or "V2_CALCULATION",
        }
    except Exception:
        return {
            "current_regime": "UNKNOWN",
            "confidence": 0.0,
            "source": "V2_CALCULATION",
        }

def _build_valuation_repair_map(security_codes: list[str]) -> dict[str, dict[str, Any]]:
    """批量查询估值修复快照，供决策工作台展示辅助信息。"""
    try:
        return get_valuation_repair_map(security_codes)
    except Exception as exc:
        logger.warning(f"Failed to build valuation repair map for decision workspace: {exc}")
        return {}

def _user_action_label(value: str) -> str:
    return build_user_action_label(value)

def _risk_checks(recommendation, market_price: Decimal | None) -> dict[str, Any]:
    return build_recommendation_risk_checks(recommendation, market_price)

def _serialize_transition_plan(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    return serialize_transition_plan_payload(plan)

def _pulse_context() -> dict[str, Any]:
    try:
        snapshot = GetLatestPulseUseCase().execute(
            as_of_date=date.today(),
            require_reliable=True,
            refresh_if_stale=True,
        )
    except Exception as exc:
        logger.warning(f"Failed to load pulse context for invalidation template: {exc}")
        snapshot = None

    if snapshot is None:
        return {
            "observed_at": None,
            "composite_score": 0.0,
            "regime_strength": "unknown",
            "transition_warning": False,
            "transition_direction": "",
            "transition_reasons": [],
        }

    return {
        "observed_at": snapshot.observed_at.isoformat(),
        "composite_score": snapshot.composite_score,
        "regime_strength": snapshot.regime_strength,
        "transition_warning": snapshot.transition_warning,
        "transition_direction": snapshot.transition_direction,
        "transition_reasons": snapshot.transition_reasons,
    }

def _build_system_invalidation_template(
    security_code: str,
    side: str,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    regime = _regime_context()
    pulse = _pulse_context()

    pulse_threshold = round(min(float(pulse.get("composite_score", 0.0) or 0.0) - 0.15, -0.05), 2)
    confidence_floor = round(max(float(regime.get("confidence", 0.0) or 0.0) - 0.2, 0.25), 2)
    logic = "AND"
    description = "当系统脉搏和宏观判定失效时，当前交易逻辑被证伪。"
    if side == "SELL":
        logic = "OR"
        description = "当风险环境修复或宏观卖出逻辑失效时，当前减仓/清仓逻辑被证伪。"

    conditions = [
        {
            "indicator_code": "PULSE_COMPOSITE",
            "indicator_type": "pulse",
            "operator": "<" if side != "SELL" else ">",
            "threshold": pulse_threshold if side != "SELL" else max(pulse_threshold + 0.35, 0.1),
        },
        {
            "indicator_code": "REGIME_CONFIDENCE",
            "indicator_type": "regime",
            "operator": "<",
            "threshold": confidence_floor,
        },
    ]
    if pulse.get("transition_warning"):
        conditions.append(
            {
                "indicator_code": "PULSE_TRANSITION_WARNING",
                "indicator_type": "pulse",
                "operator": "==",
                "threshold": 1,
            }
        )

    return {
        "logic": logic,
        "conditions": conditions,
        "requires_user_confirmation": False,
        "meta": {
            "security_code": security_code,
            "side": side,
            "regime": regime.get("current_regime"),
            "regime_confidence": regime.get("confidence"),
            "pulse_composite_score": pulse.get("composite_score"),
            "pulse_regime_strength": pulse.get("regime_strength"),
            "transition_warning": pulse.get("transition_warning"),
            "transition_direction": pulse.get("transition_direction"),
            "transition_reasons": pulse.get("transition_reasons"),
            "rationale": rationale,
        },
        "description": description,
    }

def _extract_json_payload(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("AI 返回为空")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start:end + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回不是 JSON 对象")
    return parsed

def _load_signal_payloads(signal_ids: list[str]) -> dict[str, dict[str, Any]]:
    return get_signal_payloads(signal_ids)

def _build_plan_risk_checks(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    return workspace_build_plan_risk_checks(plan)

def _build_transition_plan_for_account(
    account_id: str,
    recommendation_ids: list[str] | None = None,
    *,
    persist: bool = True,
) -> PortfolioTransitionPlan:
    return workspace_build_transition_plan_for_account(
        account_id=account_id,
        recommendation_ids=recommendation_ids,
        persist=persist,
    )

def _update_transition_plan_from_payload(
    plan: PortfolioTransitionPlan,
    payload: dict[str, Any],
) -> PortfolioTransitionPlan:
    order_updates = payload.get("orders") or []
    order_update_map = {
        (
            str(item.get("source_recommendation_id") or ""),
            str(item.get("security_code") or ""),
        ): item
        for item in order_updates
    }
    updated_orders: list[TransitionOrder] = []
    for order in plan.orders:
        patch = order_update_map.get((order.source_recommendation_id, order.security_code), {})
        invalidation_rule = patch.get("invalidation_rule", order.invalidation_rule)
        if invalidation_rule is None:
            invalidation_rule = {}
        updated_order = replace(
            order,
            stop_loss_price=(
                _decimal(patch.get("stop_loss_price"), default=order.stop_loss_price)
                if "stop_loss_price" in patch
                else order.stop_loss_price
            ),
            invalidation_rule=invalidation_rule,
            invalidation_description=str(
                patch.get("invalidation_description", order.invalidation_description)
            ),
            requires_user_confirmation=bool(
                invalidation_rule.get("requires_user_confirmation", False)
            ),
            review_by=patch.get("review_by", order.review_by),
        )
        updated_orders.append(updated_order)

    updated_plan = replace(
        plan,
        orders=updated_orders,
        risk_contract=payload.get("risk_contract", plan.risk_contract),
        status=TransitionPlanStatus.DRAFT,
    )
    if updated_plan.can_enter_approval:
        updated_plan = replace(updated_plan, status=TransitionPlanStatus.READY_FOR_APPROVAL)
    return updated_plan

def _create_approval_from_plan(
    plan: PortfolioTransitionPlan,
    account_id: str,
    risk_checks: dict[str, Any],
    regime_source: str,
    market_price: Decimal | None,
):
    return create_plan_approval(
        plan,
        account_id=account_id,
        risk_checks=risk_checks,
        regime_source=regime_source,
        market_price=market_price,
    )

