"""Decision Rhythm API views for valuation pricing and execution approval workflow."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.current_regime import resolve_current_regime
from apps.pulse.application.use_cases import GetLatestPulseUseCase
from apps.ai_provider.infrastructure.client_factory import AIClientFactory

from ..domain.entities import (
    ApprovalStatus,
    PortfolioTransitionPlan,
    QuotaPeriod,
    RecommendationStatus,
    TransitionOrder,
    TransitionPlanStatus,
    UserDecisionAction,
    create_portfolio_transition_plan,
    create_execution_approval_request,
)
from ..domain.services import (
    ApprovalStatusStateMachine,
    ExecutionApprovalService,
    RecommendationConsolidationService,
    ValuationSnapshotService,
)
from ..infrastructure.repositories import (
    CooldownRepository,
    ExecutionApprovalRequestRepository,
    InvestmentRecommendationRepository,
    PortfolioTransitionPlanRepository,
    QuotaRepository,
    ValuationSnapshotRepository,
)

logger = logging.getLogger(__name__)


def _decimal(value: Any, *, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


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
    codes = [(code or "").upper() for code in security_codes if code]
    if not codes:
        return {}

    try:
        from apps.equity.infrastructure.models import ValuationRepairTrackingModel

        records = ValuationRepairTrackingModel._default_manager.filter(
            stock_code__in=codes,
            is_active=True,
        ).values(
            "stock_code",
            "current_phase",
            "signal",
            "composite_percentile",
            "repair_progress",
            "repair_speed_per_30d",
            "estimated_days_to_target",
            "confidence",
            "as_of_date",
            "is_stalled",
        )
        return {
            str(row["stock_code"]).upper(): {
                "phase": row.get("current_phase"),
                "signal": row.get("signal"),
                "composite_percentile": row.get("composite_percentile"),
                "repair_progress": row.get("repair_progress"),
                "repair_speed_per_30d": row.get("repair_speed_per_30d"),
                "estimated_days_to_target": row.get("estimated_days_to_target"),
                "confidence": row.get("confidence"),
                "is_stalled": row.get("is_stalled"),
                "as_of_date": row["as_of_date"].isoformat() if row.get("as_of_date") else None,
            }
            for row in records
        }
    except Exception as exc:
        logger.warning(f"Failed to build valuation repair map for decision workspace: {exc}")
        return {}


def _user_action_label(value: str) -> str:
    return {
        UserDecisionAction.PENDING.value: "待决策",
        UserDecisionAction.WATCHING.value: "观察中",
        UserDecisionAction.ADOPTED.value: "已采纳",
        UserDecisionAction.IGNORED.value: "已忽略",
    }.get(value, value)


def _risk_checks(recommendation, market_price: Decimal | None) -> dict[str, Any]:
    result: dict[str, Any] = {}

    if market_price is None:
        result["price_validation"] = {"passed": True, "reason": "未提供市场价"}
    elif recommendation.is_buy:
        passed = market_price <= recommendation.entry_price_high
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 高于入场上限 {recommendation.entry_price_high}",
        }
    elif recommendation.is_sell:
        passed = market_price >= recommendation.target_price_low
        result["price_validation"] = {
            "passed": passed,
            "reason": "" if passed else f"市场价格 {market_price} 低于目标下限 {recommendation.target_price_low}",
        }
    else:
        result["price_validation"] = {"passed": True, "reason": "HOLD 无价格限制"}

    try:
        quota = QuotaRepository().get_quota(QuotaPeriod.WEEKLY)
        quota_ok = bool(quota and not quota.is_quota_exceeded)
        result["quota"] = {
            "passed": quota_ok,
            "remaining": quota.remaining_decisions if quota else 0,
            "reason": "" if quota_ok else "周配额不足",
        }
    except Exception as exc:
        result["quota"] = {"passed": True, "reason": f"quota check skipped: {exc}"}

    try:
        cooldown = CooldownRepository().get_active_cooldown(recommendation.security_code)
        cooldown_ok = not cooldown or cooldown.is_decision_ready
        result["cooldown"] = {
            "passed": cooldown_ok,
            "hours_remaining": cooldown.decision_ready_in_hours if cooldown else 0,
            "reason": "" if cooldown_ok else f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时",
        }
    except Exception as exc:
        result["cooldown"] = {"passed": True, "reason": f"cooldown check skipped: {exc}"}

    return result


def _serialize_transition_plan(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    return plan.to_dict()


def _pulse_context() -> dict[str, Any]:
    try:
        snapshot = GetLatestPulseUseCase().execute()
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
    normalized_ids = [int(signal_id) for signal_id in signal_ids if str(signal_id).isdigit()]
    if not normalized_ids:
        return {}

    from apps.signal.infrastructure.models import InvestmentSignalModel

    rows = InvestmentSignalModel.objects.filter(id__in=normalized_ids).values(
        "id",
        "invalidation_rule_json",
        "invalidation_description",
        "invalidation_logic",
    )
    return {
        str(row["id"]): {
            "invalidation_rule_json": row.get("invalidation_rule_json") or {},
            "invalidation_description": row.get("invalidation_description") or "",
            "invalidation_logic": row.get("invalidation_logic") or "",
        }
        for row in rows
    }


def _build_plan_risk_checks(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    risk_checks: dict[str, Any] = {
        "plan_validation": {
            "passed": plan.can_enter_approval,
            "reason": "" if plan.can_enter_approval else "；".join(plan.blocking_issues),
        }
    }

    try:
        quota = QuotaRepository().get_quota(QuotaPeriod.WEEKLY)
        quota_ok = bool(quota and not quota.is_quota_exceeded)
        risk_checks["quota"] = {
            "passed": quota_ok,
            "remaining": quota.remaining_decisions if quota else 0,
            "reason": "" if quota_ok else "周配额不足",
        }
    except Exception as exc:
        risk_checks["quota"] = {"passed": True, "reason": f"quota check skipped: {exc}"}

    cooldown_failures: list[str] = []
    cooldown_repo = CooldownRepository()
    for order in plan.orders:
        if order.action == "HOLD":
            continue
        try:
            cooldown = cooldown_repo.get_active_cooldown(order.security_code)
            if cooldown and not cooldown.is_decision_ready:
                cooldown_failures.append(
                    f"{order.security_code}: 剩余 {cooldown.decision_ready_in_hours:.1f} 小时"
                )
        except Exception:
            continue

    risk_checks["cooldown"] = {
        "passed": not cooldown_failures,
        "reason": "" if not cooldown_failures else "；".join(cooldown_failures),
    }
    return risk_checks


def _build_transition_plan_for_account(
    account_id: str,
    recommendation_ids: list[str] | None = None,
    *,
    persist: bool = True,
) -> PortfolioTransitionPlan:
    from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel
    from apps.simulated_trading.infrastructure.models import PositionModel

    recommendation_queryset = UnifiedRecommendationModel.objects.filter(account_id=account_id).order_by("-created_at")
    if recommendation_ids:
        recommendation_queryset = recommendation_queryset.filter(recommendation_id__in=recommendation_ids)
    else:
        recommendation_queryset = recommendation_queryset.filter(user_action=UserDecisionAction.ADOPTED.value)

    recommendation_models = list(recommendation_queryset)
    if not recommendation_models:
        raise ValueError("当前账户没有可生成交易计划的已采纳推荐")

    signal_ids = sorted(
        {
            str(signal_id)
            for recommendation in recommendation_models
            for signal_id in (recommendation.source_signal_ids or [])
            if signal_id
        }
    )
    signal_payloads = _load_signal_payloads(signal_ids)

    current_positions = list(
        PositionModel.objects.filter(account_id=account_id).values(
            "asset_code",
            "asset_name",
            "quantity",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl_pct",
        )
    )
    plan = create_portfolio_transition_plan(
        account_id=account_id,
        recommendations=[recommendation.to_domain() for recommendation in recommendation_models],
        current_positions=current_positions,
        signal_payloads=signal_payloads,
    )
    if persist:
        plan = PortfolioTransitionPlanRepository().save(plan)
    return plan


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
    from uuid import uuid4

    from apps.decision_rhythm.infrastructure.models import (
        ExecutionApprovalRequestModel,
        PortfolioTransitionPlanModel,
    )

    pending_exists = ExecutionApprovalRequestModel.objects.filter(
        transition_plan__plan_id=plan.plan_id,
        approval_status=ApprovalStatus.PENDING.value,
    ).exists()
    if pending_exists:
        raise ValueError("当前交易计划已存在待审批请求")

    plan_model = PortfolioTransitionPlanModel.objects.get(plan_id=plan.plan_id)
    active_orders = [order for order in plan.orders if order.action != "HOLD"]
    total_quantity = sum(abs(order.delta_qty) for order in active_orders) or 1
    price_lows = [order.price_band_low for order in active_orders] or [Decimal("0")]
    price_highs = [order.price_band_high for order in active_orders] or [Decimal("0")]

    approval_model = ExecutionApprovalRequestModel.objects.create(
        request_id=f"apr_{uuid4().hex[:12]}",
        transition_plan=plan_model,
        account_id=account_id,
        security_code="PLAN",
        side="HOLD",
        approval_status=ApprovalStatus.PENDING.value,
        suggested_quantity=total_quantity,
        market_price_at_review=market_price,
        price_range_low=min(price_lows),
        price_range_high=max(price_highs),
        stop_loss_price=Decimal("0"),
        risk_check_results=risk_checks,
        reviewer_comments="",
        regime_source=regime_source,
        execution_params_json={
            "preview_type": "transition_plan",
            "plan_snapshot": plan.to_dict(),
        },
    )
    plan_model.status = TransitionPlanStatus.APPROVAL_PENDING.value
    plan_model.approval_request_id = approval_model.request_id
    plan_model.save(update_fields=["status", "approval_request_id", "updated_at"])
    return approval_model.to_domain()


class ValuationSnapshotDetailView(APIView):
    """GET /api/valuation/snapshot/{snapshot_id}/"""

    def get(self, request, snapshot_id: str) -> Response:
        snapshot = ValuationSnapshotRepository().get_by_id(snapshot_id)
        if snapshot is None:
            return Response({"success": False, "error": "Valuation snapshot not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": snapshot.to_dict()})


class ValuationRecalculateView(APIView):
    """POST /api/valuation/recalculate/"""

    def post(self, request) -> Response:
        security_code = (request.data or {}).get("security_code")
        if not security_code:
            return Response({"success": False, "error": "security_code is required"}, status=status.HTTP_400_BAD_REQUEST)

        valuation_method = (request.data or {}).get("valuation_method", "COMPOSITE")
        fair_value = _decimal((request.data or {}).get("fair_value"))
        current_price = _decimal((request.data or {}).get("current_price"))
        if fair_value is None and current_price is None:
            return Response(
                {"success": False, "error": "fair_value or current_price is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fair_value = fair_value or current_price
        current_price = current_price or fair_value

        snapshot = ValuationSnapshotService().create_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=(request.data or {}).get("input_parameters") or {"source": "api_recalculate"},
        )
        snapshot = ValuationSnapshotRepository().save(snapshot)
        return Response({"success": True, "data": snapshot.to_dict()}, status=status.HTTP_201_CREATED)


class AggregatedWorkspaceView(APIView):
    """GET /api/decision/workspace/aggregated/"""

    def get(self, request) -> Response:
        repo = InvestmentRecommendationRepository()
        recommendations = repo.get_active_recommendations()

        account_id = request.query_params.get("account_id")
        if account_id:
            recommendations = [
                rec for rec in recommendations if getattr(rec, "account_id", "default") == account_id
            ]

        consolidated = RecommendationConsolidationService().consolidate(
            recommendations=recommendations,
            account_id=account_id or "default",
        )

        payload = []
        for rec in consolidated:
            payload.append(
                {
                    "aggregation_key": f"{getattr(rec, 'account_id', account_id or 'default')}:{rec.security_code}:{rec.side}",
                    "security_code": rec.security_code,
                    "side": rec.side,
                    "confidence": rec.confidence,
                    "valuation_snapshot_id": rec.valuation_snapshot_id,
                    "price_range": {
                        "entry_low": str(rec.entry_price_low),
                        "entry_high": str(rec.entry_price_high),
                        "target_low": str(rec.target_price_low),
                        "target_high": str(rec.target_price_high),
                        "stop_loss": str(rec.stop_loss_price),
                    },
                    "position_suggestion": {
                        "suggested_pct": rec.position_size_pct,
                        "suggested_quantity": rec.suggested_quantity,
                        "max_capital": str(rec.max_capital),
                    },
                    "reason_codes": rec.reason_codes,
                    "human_readable_rationale": rec.human_readable_rationale,
                    "source_recommendation_ids": rec.source_recommendation_ids,
                }
            )

        return Response(
            {
                "success": True,
                "data": {
                    "aggregated_recommendations": payload,
                    "regime_context": _regime_context(),
                },
            }
        )


class TransitionPlanGenerateView(APIView):
    """POST /api/decision/workspace/plans/generate/"""

    def post(self, request) -> Response:
        account_id = (request.data or {}).get("account_id") or "default"
        recommendation_ids = (request.data or {}).get("recommendation_ids") or None

        try:
            plan = _build_transition_plan_for_account(
                account_id=account_id,
                recommendation_ids=recommendation_ids,
                persist=True,
            )
        except ValueError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.error(f"Failed to generate transition plan: {exc}", exc_info=True)
            return Response({"success": False, "error": "生成交易计划失败"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"success": True, "data": _serialize_transition_plan(plan)}, status=status.HTTP_201_CREATED)


class TransitionPlanDetailView(APIView):
    """GET /api/decision/workspace/plans/<str:plan_id>/"""

    def get(self, request, plan_id: str) -> Response:
        plan = PortfolioTransitionPlanRepository().get_by_id(plan_id)
        if plan is None:
            return Response({"success": False, "error": "Transition plan not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": _serialize_transition_plan(plan)})


class TransitionPlanUpdateView(APIView):
    """POST /api/decision/workspace/plans/<str:plan_id>/update/"""

    def post(self, request, plan_id: str) -> Response:
        repo = PortfolioTransitionPlanRepository()
        plan = repo.get_by_id(plan_id)
        if plan is None:
            return Response({"success": False, "error": "Transition plan not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            updated_plan = _update_transition_plan_from_payload(plan, request.data or {})
            updated_plan = repo.save(updated_plan)
        except Exception as exc:
            logger.error(f"Failed to update transition plan {plan_id}: {exc}", exc_info=True)
            return Response({"success": False, "error": "更新交易计划失败"}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"success": True, "data": _serialize_transition_plan(updated_plan)})


class InvalidationTemplateView(APIView):
    """POST /api/decision/workspace/invalidation/template/"""

    def post(self, request) -> Response:
        security_code = str((request.data or {}).get("security_code") or "").strip().upper()
        side = str((request.data or {}).get("side") or "BUY").strip().upper()
        rationale = str((request.data or {}).get("rationale") or "").strip()

        if not security_code:
            return Response({"success": False, "error": "security_code is required"}, status=status.HTTP_400_BAD_REQUEST)

        template = _build_system_invalidation_template(
            security_code=security_code,
            side=side,
            rationale=rationale,
        )
        return Response(
            {
                "success": True,
                "data": {
                    "template": template,
                    "pulse_context": _pulse_context(),
                    "regime_context": _regime_context(),
                },
            }
        )


class InvalidationAIDraftView(APIView):
    """POST /api/decision/workspace/invalidation/ai-draft/"""

    def post(self, request) -> Response:
        security_code = str((request.data or {}).get("security_code") or "").strip().upper()
        side = str((request.data or {}).get("side") or "BUY").strip().upper()
        rationale = str((request.data or {}).get("rationale") or "").strip()
        user_prompt = str((request.data or {}).get("user_prompt") or "").strip()
        existing_rule = (request.data or {}).get("existing_rule") or {}

        if not security_code:
            return Response({"success": False, "error": "security_code is required"}, status=status.HTTP_400_BAD_REQUEST)

        pulse = _pulse_context()
        regime = _regime_context()
        system_template = _build_system_invalidation_template(
            security_code=security_code,
            side=side,
            rationale=rationale,
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "你是投资系统的证伪逻辑助手。只返回一个 JSON 对象。"
                    "字段必须包含 logic, conditions, requires_user_confirmation, description。"
                    "conditions 中每项必须包含 indicator_code, indicator_type, operator, threshold。"
                    "不要输出 Markdown，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "生成适用于交易计划审批前的证伪逻辑草稿",
                        "security_code": security_code,
                        "side": side,
                        "rationale": rationale,
                        "user_prompt": user_prompt,
                        "existing_rule": existing_rule,
                        "pulse_context": pulse,
                        "regime_context": regime,
                        "system_template": system_template,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        ai_client = AIClientFactory().get_client()
        ai_response = ai_client.chat_completion(messages=messages, temperature=0.2, max_tokens=500)
        if ai_response.get("status") != "success":
            return Response(
                {
                    "success": False,
                    "error": ai_response.get("error_message") or "AI 生成失败",
                    "fallback_template": system_template,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            draft = _extract_json_payload(ai_response.get("content", ""))
        except Exception as exc:
            return Response(
                {
                    "success": False,
                    "error": f"AI 返回解析失败: {exc}",
                    "fallback_template": system_template,
                    "raw_content": ai_response.get("content", ""),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        draft.setdefault("logic", "AND")
        draft.setdefault("conditions", [])
        draft.setdefault("requires_user_confirmation", False)
        draft.setdefault("description", "AI 生成的证伪草稿")
        draft.setdefault("meta", {})
        draft["meta"]["security_code"] = security_code
        draft["meta"]["side"] = side
        draft["meta"]["pulse_context"] = pulse
        draft["meta"]["regime_context"] = regime

        return Response(
            {
                "success": True,
                "data": {
                    "draft": draft,
                    "pulse_context": pulse,
                    "regime_context": regime,
                    "provider_used": ai_response.get("provider_used", ""),
                    "model": ai_response.get("model", ""),
                },
            }
        )


class ExecutionPreviewView(APIView):
    """POST /api/decision/execute/preview/"""

    def post(self, request) -> Response:
        plan_id = (request.data or {}).get("plan_id")
        recommendation_id = (request.data or {}).get("recommendation_id")
        account_id = (request.data or {}).get("account_id") or "default"
        market_price = _decimal((request.data or {}).get("market_price"))

        if plan_id:
            plan_repo = PortfolioTransitionPlanRepository()
            plan = plan_repo.get_by_id(plan_id)
            if plan is None:
                return Response({"success": False, "error": "Transition plan not found"}, status=status.HTTP_404_NOT_FOUND)

            risk_checks = _build_plan_risk_checks(plan)
            if not risk_checks["plan_validation"]["passed"]:
                return Response(
                    {
                        "success": False,
                        "error": risk_checks["plan_validation"]["reason"],
                        "blocking_issues": plan.blocking_issues,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            regime_source = _regime_context()["source"]
            try:
                approval_request = _create_approval_from_plan(
                    plan=plan,
                    account_id=account_id,
                    risk_checks=risk_checks,
                    regime_source=regime_source,
                    market_price=market_price,
                )
            except ValueError as exc:
                return Response({"success": False, "error": str(exc)}, status=status.HTTP_409_CONFLICT)

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": approval_request.request_id,
                        "plan_id": plan.plan_id,
                        "recommendation_type": "plan",
                        "preview": {
                            "orders_count": len(plan.orders),
                            "active_orders_count": len([order for order in plan.orders if order.action != "HOLD"]),
                            "summary": plan.summary,
                            "risk_contract": plan.risk_contract,
                        },
                        "risk_checks": risk_checks,
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        if not recommendation_id:
            return Response({"success": False, "error": "plan_id or recommendation_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 优先查找 UnifiedRecommendation（M2 融合推荐）
        from ..domain.entities import UnifiedRecommendation
        from ..infrastructure.models import UnifiedRecommendationModel

        uni_rec_model = UnifiedRecommendationModel.objects.filter(
            recommendation_id=recommendation_id
        ).first()

        if uni_rec_model:
            # 使用 UnifiedRecommendation 创建审批请求
            uni_rec = uni_rec_model.to_domain()

            # 检查是否有待审批请求
            approval_repo = ExecutionApprovalRequestRepository()
            if approval_repo.has_pending_request(account_id, uni_rec.security_code, uni_rec.side):
                return Response(
                    {"success": False, "error": "Pending request already exists for this account/security/side"},
                    status=status.HTTP_409_CONFLICT,
                )

            # 构建 risk_checks
            risk_checks = self._risk_checks_from_unified(uni_rec, market_price)
            regime_source = _regime_context()["source"]

            # 创建审批请求（关联 UnifiedRecommendation）
            approval_request = self._create_approval_from_unified(
                uni_rec=uni_rec,
                uni_rec_model=uni_rec_model,
                account_id=account_id,
                risk_checks=risk_checks,
                regime_source=regime_source,
                market_price=market_price,
            )

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": approval_request.request_id,
                        "recommendation_id": uni_rec.recommendation_id,
                        "recommendation_type": "unified",
                        "preview": {
                            "security_code": uni_rec.security_code,
                            "side": uni_rec.side,
                            "confidence": uni_rec.confidence,
                            "composite_score": uni_rec.composite_score,
                            "fair_value": str(uni_rec.fair_value),
                            "price_range": {
                                "entry_low": str(uni_rec.entry_price_low),
                                "entry_high": str(uni_rec.entry_price_high),
                                "target_low": str(uni_rec.target_price_low),
                                "target_high": str(uni_rec.target_price_high),
                                "stop_loss": str(uni_rec.stop_loss_price),
                            },
                            "position_suggestion": {
                                "suggested_pct": uni_rec.position_pct,
                                "suggested_quantity": uni_rec.suggested_quantity,
                                "max_capital": str(uni_rec.max_capital),
                            },
                            "regime_source": regime_source,
                        },
                        "risk_checks": risk_checks,
                    },
                },
                status=status.HTTP_201_CREATED,
            )

        # 回退到旧版 InvestmentRecommendation
        rec_repo = InvestmentRecommendationRepository()
        recommendation = rec_repo.get_by_id(recommendation_id)
        if recommendation is None:
            return Response({"success": False, "error": "Recommendation not found"}, status=status.HTTP_404_NOT_FOUND)

        risk_checks = _risk_checks(recommendation, market_price)
        regime_source = _regime_context()["source"]

        approval_repo = ExecutionApprovalRequestRepository()
        if approval_repo.has_pending_request(account_id, recommendation.security_code, recommendation.side):
            return Response(
                {"success": False, "error": "Pending request already exists for this account/security/side"},
                status=status.HTTP_409_CONFLICT,
            )

        approval_request = create_execution_approval_request(
            recommendation=recommendation,
            account_id=account_id,
            risk_check_results=risk_checks,
            regime_source=regime_source,
            market_price_at_review=market_price,
        )
        approval_request = approval_repo.save(approval_request)

        return Response(
            {
                "success": True,
                "data": {
                    "request_id": approval_request.request_id,
                    "recommendation_id": recommendation.recommendation_id,
                    "recommendation_type": "legacy",
                    "valuation_snapshot_id": recommendation.valuation_snapshot_id,
                    "preview": {
                        "security_code": recommendation.security_code,
                        "side": recommendation.side,
                        "confidence": recommendation.confidence,
                        "fair_value": str(recommendation.fair_value),
                        "price_range": recommendation.price_range,
                        "position_suggestion": {
                            "suggested_pct": recommendation.position_size_pct,
                            "suggested_quantity": recommendation.suggested_quantity,
                            "max_capital": str(recommendation.max_capital),
                        },
                        "regime_source": regime_source,
                    },
                    "risk_checks": risk_checks,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    def _risk_checks_from_unified(self, uni_rec, market_price) -> dict[str, Any]:
        """从 UnifiedRecommendation 构建风控检查结果"""
        result = {}

        if market_price is None:
            result["price_validation"] = {"passed": True, "reason": "未提供市场价"}
        elif uni_rec.side == "BUY":
            passed = market_price <= uni_rec.entry_price_high
            result["price_validation"] = {
                "passed": passed,
                "reason": "" if passed else f"市场价格 {market_price} 高于入场上限 {uni_rec.entry_price_high}",
            }
        elif uni_rec.side == "SELL":
            passed = market_price >= uni_rec.target_price_low
            result["price_validation"] = {
                "passed": passed,
                "reason": "" if passed else f"市场价格 {market_price} 低于目标下限 {uni_rec.target_price_low}",
            }
        else:
            result["price_validation"] = {"passed": True, "reason": "HOLD 无价格限制"}

        # Beta Gate 检查
        result["beta_gate"] = {
            "passed": uni_rec.beta_gate_passed,
            "reason": "" if uni_rec.beta_gate_passed else "Beta Gate 未通过",
        }

        # 配额检查
        try:
            quota = QuotaRepository().get_quota(QuotaPeriod.WEEKLY)
            quota_ok = bool(quota and not quota.is_quota_exceeded)
            result["quota"] = {
                "passed": quota_ok,
                "remaining": quota.remaining_decisions if quota else 0,
                "reason": "" if quota_ok else "周配额不足",
            }
        except Exception as exc:
            result["quota"] = {"passed": True, "reason": f"quota check skipped: {exc}"}

        # 冷却检查
        try:
            cooldown = CooldownRepository().get_active_cooldown(uni_rec.security_code)
            cooldown_ok = not cooldown or cooldown.is_decision_ready
            result["cooldown"] = {
                "passed": cooldown_ok,
                "hours_remaining": cooldown.decision_ready_in_hours if cooldown else 0,
                "reason": "" if cooldown_ok else f"冷却期内，剩余 {cooldown.decision_ready_in_hours:.1f} 小时",
            }
        except Exception as exc:
            result["cooldown"] = {"passed": True, "reason": f"cooldown check skipped: {exc}"}

        return result

    def _create_approval_from_unified(
        self, uni_rec, uni_rec_model, account_id, risk_checks, regime_source, market_price
    ):
        """从 UnifiedRecommendation 创建审批请求"""
        from datetime import datetime, timezone
        from uuid import uuid4

        from ..infrastructure.models import ExecutionApprovalRequestModel

        # 计算建议数量
        entry_mid = (uni_rec.entry_price_low + uni_rec.entry_price_high) / 2
        if entry_mid > 0:
            suggested_qty = int(uni_rec.max_capital / entry_mid)
        else:
            suggested_qty = 0

        approval_model = ExecutionApprovalRequestModel(
            request_id=f"apr_{uuid4().hex[:12]}",
            unified_recommendation=uni_rec_model,
            transition_plan=None,
            account_id=account_id,
            security_code=uni_rec.security_code,
            side=uni_rec.side,
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=suggested_qty,
            market_price_at_review=market_price,
            price_range_low=uni_rec.entry_price_low,
            price_range_high=uni_rec.entry_price_high,
            stop_loss_price=uni_rec.stop_loss_price,
            risk_check_results=risk_checks,
            reviewer_comments="",
            regime_source=regime_source,
            created_at=datetime.now(UTC),
        )
        approval_model.save()

        # 更新 UnifiedRecommendation 状态为 REVIEWING
        uni_rec_model.status = "REVIEWING"
        uni_rec_model.save(update_fields=["status", "updated_at"])

        return approval_model.to_domain()


class ExecutionApproveView(APIView):
    """POST /api/decision/execute/approve/"""

    def post(self, request) -> Response:
        request_id = (request.data or {}).get("approval_request_id")
        reviewer_comments = (request.data or {}).get("reviewer_comments", "")
        market_price = _decimal((request.data or {}).get("market_price"))

        if not request_id:
            return Response({"success": False, "error": "approval_request_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        repo = ExecutionApprovalRequestRepository()
        approval_request = repo.get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_approve, reason = ExecutionApprovalService().can_approve(
            approval_request,
            market_price or approval_request.market_price_at_review or Decimal("0"),
        )
        if not can_approve:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.APPROVED,
            reviewer_comments=reviewer_comments,
        )

        # 发布决策批准事件（触发 Candidate 状态同步）
        self._publish_decision_approved_event(updated)

        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})

    def _publish_decision_approved_event(self, approval_request):
        """发布决策批准事件，同步 Candidate 状态"""
        try:
            from apps.events.domain.entities import EventType, create_event
            from apps.events.domain.services import get_event_bus

            event_bus = get_event_bus()

            # 获取关联的 candidate_id
            from ..infrastructure.models import ExecutionApprovalRequestModel
            from ..infrastructure.models import UnifiedRecommendationModel
            model = ExecutionApprovalRequestModel.objects.get(request_id=approval_request.request_id)

            candidate_ids = []
            if model.unified_recommendation:
                candidate_ids = model.unified_recommendation.source_candidate_ids or []
            elif model.transition_plan:
                source_ids = model.transition_plan.source_recommendation_ids or []
                candidate_ids = list(
                    UnifiedRecommendationModel.objects.filter(recommendation_id__in=source_ids)
                    .values_list("source_candidate_ids", flat=True)
                )
                candidate_ids = [
                    candidate_id
                    for group in candidate_ids
                    for candidate_id in (group or [])
                ]

            if candidate_ids:
                event = create_event(
                    event_type=EventType.DECISION_APPROVED,
                    payload={
                        "request_id": approval_request.request_id,
                        "recommendation_id": approval_request.recommendation_id,
                        "candidate_ids": candidate_ids,
                        "security_code": approval_request.security_code,
                        "side": approval_request.side,
                        "reviewer_comments": approval_request.reviewer_comments,
                    },
                )
                event_bus.publish(event)
                logger.info(f"Published DECISION_APPROVED event for request {approval_request.request_id}")
        except Exception as e:
            logger.error(f"Failed to publish DECISION_APPROVED event: {e}", exc_info=True)


class ExecutionRejectView(APIView):
    """POST /api/decision/execute/reject/"""

    def post(self, request) -> Response:
        request_id = (request.data or {}).get("approval_request_id")
        reviewer_comments = (request.data or {}).get("reviewer_comments", "")

        if not request_id:
            return Response({"success": False, "error": "approval_request_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        repo = ExecutionApprovalRequestRepository()
        approval_request = repo.get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_transition, reason = ApprovalStatusStateMachine.validate_transition(
            approval_request.approval_status,
            ApprovalStatus.REJECTED,
        )
        if not can_transition:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.REJECTED,
            reviewer_comments=reviewer_comments,
        )

        # 发布决策拒绝事件
        self._publish_decision_rejected_event(updated)

        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})

    def _publish_decision_rejected_event(self, approval_request):
        """发布决策拒绝事件"""
        try:
            from apps.events.domain.entities import EventType, create_event
            from apps.events.domain.services import get_event_bus

            event_bus = get_event_bus()

            # 获取关联的 candidate_id
            from ..infrastructure.models import ExecutionApprovalRequestModel
            from ..infrastructure.models import UnifiedRecommendationModel
            model = ExecutionApprovalRequestModel.objects.get(request_id=approval_request.request_id)

            candidate_ids = []
            if model.unified_recommendation:
                candidate_ids = model.unified_recommendation.source_candidate_ids or []
            elif model.transition_plan:
                source_ids = model.transition_plan.source_recommendation_ids or []
                candidate_ids = list(
                    UnifiedRecommendationModel.objects.filter(recommendation_id__in=source_ids)
                    .values_list("source_candidate_ids", flat=True)
                )
                candidate_ids = [
                    candidate_id
                    for group in candidate_ids
                    for candidate_id in (group or [])
                ]

            event = create_event(
                event_type=EventType.DECISION_REJECTED,
                payload={
                    "request_id": approval_request.request_id,
                    "recommendation_id": approval_request.recommendation_id,
                    "candidate_ids": candidate_ids,
                    "security_code": approval_request.security_code,
                    "side": approval_request.side,
                    "reviewer_comments": approval_request.reviewer_comments,
                },
            )
            event_bus.publish(event)
            logger.info(f"Published DECISION_REJECTED event for request {approval_request.request_id}")
        except Exception as e:
            logger.error(f"Failed to publish DECISION_REJECTED event: {e}", exc_info=True)


class ExecutionRequestDetailView(APIView):
    """GET /api/decision/execute/{request_id}/"""

    def get(self, request, request_id: str) -> Response:
        approval_request = ExecutionApprovalRequestRepository().get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": approval_request.to_dict()})


# ============================================================================
# 统一推荐 API 端点（Top-down + Bottom-up 融合）
# ============================================================================


from ..application.dtos import (
    ConflictDTO,
    ConflictsListDTO,
    RecommendationsListDTO,
    RefreshRecommendationsRequestDTO,
    RefreshRecommendationsResponseDTO,
    UnifiedRecommendationDTO,
)
from ..application.use_cases import (
    GenerateRecommendationsRequest,
    GenerateUnifiedRecommendationsUseCase,
    GetConflictsRequest,
    GetConflictsUseCase,
    GetModelParamsUseCase,
    GetRecommendationsRequest,
    GetUnifiedRecommendationsUseCase,
)
from ..infrastructure.models import (
    DecisionFeatureSnapshotModel,
    DecisionModelParamConfigModel,
    UnifiedRecommendationModel,
)


class UnifiedRecommendationsView(APIView):
    """
    GET /api/decision/workspace/recommendations/

    返回统一聚合建议列表。
    """

    def get(self, request) -> Response:
        """
        获取推荐列表

        Query params:
            account_id: 账户 ID（必填）
            status: 状态过滤（可选）
            page: 页码（默认 1）
            page_size: 每页大小（默认 20）
        """
        # 灰度开关检查
        from django.conf import settings
        if not getattr(settings, 'DECISION_WORKSPACE_V2_ENABLED', True):
            return Response({
                "success": False,
                "error": "Decision Workspace V2 is disabled. Use legacy /api/decision-rhythm/submit/ endpoint.",
                "feature_flag": "DECISION_WORKSPACE_V2_ENABLED",
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        status_filter = request.query_params.get("status")
        user_action_filter = request.query_params.get("user_action")
        security_code_filter = request.query_params.get("security_code")
        include_ignored = str(request.query_params.get("include_ignored", "")).lower() in {"1", "true", "yes"}
        recommendation_id = request.query_params.get("recommendation_id")
        try:
            page = int(request.query_params.get("page", 1))
            page_size = int(request.query_params.get("page_size", 20))
        except (TypeError, ValueError):
            return Response(
                {"success": False, "error": "page and page_size must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if page < 1 or page_size < 1 or page_size > 200:
            return Response(
                {"success": False, "error": "page must be >=1 and page_size must be in [1, 200]"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 查询数据库（使用 select_related 预加载 feature_snapshot 避免 N+1 查询）
            queryset = UnifiedRecommendationModel.objects.filter(
                account_id=account_id
            ).select_related('feature_snapshot')

            # 排除冲突
            queryset = queryset.exclude(status="CONFLICT")

            if not include_ignored:
                queryset = queryset.exclude(user_action=UserDecisionAction.IGNORED.value)

            # 状态过滤
            if status_filter:
                queryset = queryset.filter(status=status_filter)

            if user_action_filter:
                queryset = queryset.filter(user_action=user_action_filter)

            if security_code_filter:
                queryset = queryset.filter(security_code=security_code_filter)

            if recommendation_id:
                queryset = queryset.filter(recommendation_id=recommendation_id)

            # 排序
            queryset = queryset.order_by("-composite_score", "-created_at")

            # 分页
            total_count = queryset.count()
            start = (page - 1) * page_size
            end = start + page_size
            models = queryset[start:end]
            valuation_repair_map = _build_valuation_repair_map([model.security_code for model in models])

            # 转换为 DTO
            recommendations = []
            for model in models:
                dto = UnifiedRecommendationDTO(
                    recommendation_id=model.recommendation_id,
                    account_id=model.account_id,
                    security_code=model.security_code,
                    side=model.side,
                    regime=model.regime,
                    regime_confidence=model.regime_confidence,
                    policy_level=model.policy_level,
                    beta_gate_passed=model.beta_gate_passed,
                    sentiment_score=model.sentiment_score,
                    flow_score=model.flow_score,
                    technical_score=model.technical_score,
                    fundamental_score=model.fundamental_score,
                    alpha_model_score=model.alpha_model_score,
                    composite_score=model.composite_score,
                    confidence=model.confidence,
                    reason_codes=model.reason_codes or [],
                    human_rationale=model.human_rationale,
                    fair_value=model.fair_value,
                    entry_price_low=model.entry_price_low,
                    entry_price_high=model.entry_price_high,
                    target_price_low=model.target_price_low,
                    target_price_high=model.target_price_high,
                    stop_loss_price=model.stop_loss_price,
                    position_pct=model.position_pct,
                    suggested_quantity=model.suggested_quantity,
                    max_capital=model.max_capital,
                    source_signal_ids=model.source_signal_ids or [],
                    source_candidate_ids=model.source_candidate_ids or [],
                    feature_snapshot_id=model.feature_snapshot.snapshot_id if model.feature_snapshot else "",
                    valuation_repair=valuation_repair_map.get((model.security_code or "").upper()),
                    status=model.status,
                    user_action=model.user_action,
                    user_action_note=model.user_action_note,
                    user_action_at=model.user_action_at,
                    created_at=model.created_at,
                    updated_at=model.updated_at,
                )
                recommendations.append(dto)

            # 构建响应
            list_dto = RecommendationsListDTO(
                recommendations=recommendations,
                total_count=total_count,
                page=page,
                page_size=page_size,
            )

            return Response({
                "success": True,
                "data": list_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to get recommendations: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RecommendationUserActionView(APIView):
    """
    POST /api/decision/workspace/recommendations/action/

    为统一推荐记录用户动作状态。
    """

    ACTION_MAPPING = {
        "watch": UserDecisionAction.WATCHING,
        "adopt": UserDecisionAction.ADOPTED,
        "ignore": UserDecisionAction.IGNORED,
        "pending": UserDecisionAction.PENDING,
    }

    def post(self, request) -> Response:
        recommendation_id = (request.data or {}).get("recommendation_id")
        action = str((request.data or {}).get("action") or "").strip().lower()
        account_id = (request.data or {}).get("account_id")
        note = str((request.data or {}).get("note") or "").strip()

        if not recommendation_id:
            return Response(
                {"success": False, "error": "recommendation_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if action not in self.ACTION_MAPPING:
            return Response(
                {
                    "success": False,
                    "error": "action must be one of: watch, adopt, ignore, pending",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from ..application.dtos import UnifiedRecommendationDTO
        from ..infrastructure.models import UnifiedRecommendationModel

        queryset = UnifiedRecommendationModel.objects.filter(recommendation_id=recommendation_id)
        if account_id:
            queryset = queryset.filter(account_id=account_id)

        recommendation = queryset.select_related("feature_snapshot").first()
        if recommendation is None:
            return Response(
                {"success": False, "error": "Recommendation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        user_action = self.ACTION_MAPPING[action]
        recommendation.user_action = user_action.value
        recommendation.user_action_note = note
        recommendation.user_action_at = timezone.now()
        recommendation.save(update_fields=["user_action", "user_action_note", "user_action_at", "updated_at"])

        valuation_repair_map = _build_valuation_repair_map([recommendation.security_code])
        dto = UnifiedRecommendationDTO(
            recommendation_id=recommendation.recommendation_id,
            account_id=recommendation.account_id,
            security_code=recommendation.security_code,
            side=recommendation.side,
            regime=recommendation.regime,
            regime_confidence=recommendation.regime_confidence,
            policy_level=recommendation.policy_level,
            beta_gate_passed=recommendation.beta_gate_passed,
            sentiment_score=recommendation.sentiment_score,
            flow_score=recommendation.flow_score,
            technical_score=recommendation.technical_score,
            fundamental_score=recommendation.fundamental_score,
            alpha_model_score=recommendation.alpha_model_score,
            composite_score=recommendation.composite_score,
            confidence=recommendation.confidence,
            reason_codes=recommendation.reason_codes or [],
            human_rationale=recommendation.human_rationale,
            fair_value=recommendation.fair_value,
            entry_price_low=recommendation.entry_price_low,
            entry_price_high=recommendation.entry_price_high,
            target_price_low=recommendation.target_price_low,
            target_price_high=recommendation.target_price_high,
            stop_loss_price=recommendation.stop_loss_price,
            position_pct=recommendation.position_pct,
            suggested_quantity=recommendation.suggested_quantity,
            max_capital=recommendation.max_capital,
            source_signal_ids=recommendation.source_signal_ids or [],
            source_candidate_ids=recommendation.source_candidate_ids or [],
            feature_snapshot_id=recommendation.feature_snapshot.snapshot_id if recommendation.feature_snapshot else "",
            valuation_repair=valuation_repair_map.get((recommendation.security_code or "").upper()),
            status=recommendation.status,
            user_action=recommendation.user_action,
            user_action_note=recommendation.user_action_note,
            user_action_at=recommendation.user_action_at,
            created_at=recommendation.created_at,
            updated_at=recommendation.updated_at,
        )

        return Response(
            {
                "success": True,
                "data": {
                    "recommendation": dto.to_dict(),
                    "message": f"已更新为{_user_action_label(recommendation.user_action)}",
                },
            }
        )


class RefreshRecommendationsView(APIView):
    """
    POST /api/decision/workspace/recommendations/refresh/

    手动触发推荐重算。
    """

    def post(self, request) -> Response:
        """
        触发刷新

        Request body:
            account_id: 账户 ID（可选，不传则使用 default 账户口径）
            security_codes: 证券代码列表（可选）
            force: 是否强制刷新（默认 False）
            async_mode: 是否异步执行（默认 True）
        """
        import uuid

        from django.core.cache import cache

        from ..application.use_cases import (
            GenerateUnifiedRecommendationsUseCase,
            GetModelParamsUseCase,
        )
        from ..infrastructure.feature_providers import (
            create_candidate_provider,
            create_feature_provider,
            create_signal_provider,
            create_valuation_provider,
        )
        from ..infrastructure.repositories import (
            DecisionModelParamConfigRepository,
            UnifiedRecommendationRepository,
        )

        # 解析请求
        dto = RefreshRecommendationsRequestDTO.from_dict(request.data or {})

        try:
            # 生成任务 ID
            task_id = f"refresh_{uuid.uuid4().hex[:12]}"

            # 创建提供者和仓储
            feature_provider = create_feature_provider()
            valuation_provider = create_valuation_provider()
            signal_provider = create_signal_provider()
            candidate_provider = create_candidate_provider()
            recommendation_repo = UnifiedRecommendationRepository()

            # 创建参数用例
            param_repo = DecisionModelParamConfigRepository()
            param_use_case = GetModelParamsUseCase(param_repo=param_repo)

            # 创建生成用例
            generate_use_case = GenerateUnifiedRecommendationsUseCase(
                feature_provider=feature_provider,
                valuation_provider=valuation_provider,
                signal_provider=signal_provider,
                candidate_provider=candidate_provider,
                recommendation_repo=recommendation_repo,
                param_use_case=param_use_case,
            )

            # 执行生成
            from ..application.use_cases import GenerateRecommendationsRequest
            generate_request = GenerateRecommendationsRequest(
                account_id=dto.account_id or "default",
                security_codes=dto.security_codes,
                force_refresh=dto.force,
            )

            result = generate_use_case.execute(generate_request)

            # 构建响应
            response_dto = RefreshRecommendationsResponseDTO(
                task_id=task_id,
                status="COMPLETED" if result.success else "FAILED",
                message="刷新完成" if result.success else f"刷新失败: {result.error}",
                recommendations_count=len(result.recommendations),
                conflicts_count=len(result.conflicts),
            )

            return Response({
                "success": result.success,
                "data": response_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to refresh recommendations: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ConflictsView(APIView):
    """
    GET /api/decision/workspace/conflicts/

    返回冲突建议。
    """

    def get(self, request) -> Response:
        """
        获取冲突列表

        Query params:
            account_id: 账户 ID（必填）
        """
        account_id = request.query_params.get("account_id")
        if not account_id:
            return Response(
                {"success": False, "error": "account_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 查询冲突推荐
            conflicts_models = UnifiedRecommendationModel.objects.filter(
                account_id=account_id,
                status="CONFLICT",
            ).order_by("-created_at")

            # 按 security_code 分组，构建 ConflictDTO
            from collections import defaultdict
            security_groups = defaultdict(list)
            for model in conflicts_models:
                security_groups[model.security_code].append(model)

            conflicts = []
            for security_code, models in security_groups.items():
                buy_rec = None
                sell_rec = None

                for model in models:
                    dto = UnifiedRecommendationDTO(
                        recommendation_id=model.recommendation_id,
                        account_id=model.account_id,
                        security_code=model.security_code,
                        side=model.side,
                        composite_score=model.composite_score,
                        confidence=model.confidence,
                        status=model.status,
                    )

                    if model.side == "BUY":
                        buy_rec = dto
                    elif model.side == "SELL":
                        sell_rec = dto

                if buy_rec or sell_rec:
                    conflict_dto = ConflictDTO(
                        security_code=security_code,
                        account_id=account_id,
                        buy_recommendation=buy_rec,
                        sell_recommendation=sell_rec,
                        conflict_type="BUY_SELL_CONFLICT",
                        resolution_hint="需要人工判断方向",
                    )
                    conflicts.append(conflict_dto)

            # 构建响应
            list_dto = ConflictsListDTO(
                conflicts=conflicts,
                total_count=len(conflicts),
            )

            return Response({
                "success": True,
                "data": list_dto.to_dict(),
            })

        except Exception as e:
            logger.error(f"Failed to get conflicts: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ModelParamsView(APIView):
    """
    GET /api/decision/workspace/params/

    获取当前模型参数配置。
    """

    def get(self, request) -> Response:
        """
        获取参数配置

        Query params:
            env: 环境（默认 dev）
        """
        env = request.query_params.get("env", "dev")

        try:
            # 查询激活的参数
            configs = DecisionModelParamConfigModel.objects.filter(
                env=env,
                is_active=True,
            ).order_by("param_key")

            params = {}
            for config in configs:
                params[config.param_key] = {
                    "value": config.param_value,
                    "type": config.param_type,
                    "description": config.description,
                    "updated_by": config.updated_by,
                    "updated_at": config.updated_at.isoformat() if config.updated_at else None,
                }

            return Response({
                "success": True,
                "data": {
                    "env": env,
                    "params": params,
                },
            })

        except Exception as e:
            logger.error(f"Failed to get model params: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class UpdateModelParamView(APIView):
    """
    POST /api/decision/workspace/params/update/

    更新模型参数。
    """

    def post(self, request) -> Response:
        """
        更新参数

        Request body:
            param_key: 参数键（必填）
            param_value: 参数值（必填）
            param_type: 参数类型（默认 float）
            env: 环境（默认 dev）
            updated_reason: 变更原因（必填）
        """
        from ..infrastructure.models import DecisionModelParamAuditLogModel

        param_key = request.data.get("param_key")
        param_value = request.data.get("param_value")
        param_type = request.data.get("param_type", "float")
        env = request.data.get("env", "dev")
        updated_reason = request.data.get("updated_reason", "")

        if not param_key or param_value is None:
            return Response(
                {"success": False, "error": "param_key and param_value are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 查找当前激活的配置（避免 MultipleObjectsReturned）
            active_config = DecisionModelParamConfigModel.objects.filter(
                param_key=param_key,
                env=env,
                is_active=True,
            ).order_by("-version").first()

            old_value = ""
            if active_config:
                # 记录旧值
                old_value = active_config.param_value
                # 失活旧配置
                active_config.is_active = False
                active_config.save(update_fields=["is_active"])
                new_version = active_config.version + 1
            else:
                new_version = 1

            # 创建新版本配置
            new_config = DecisionModelParamConfigModel.objects.create(
                param_key=param_key,
                param_value=str(param_value),
                param_type=param_type,
                env=env,
                version=new_version,
                is_active=True,
                updated_by=request.user.username if hasattr(request, "user") and request.user.is_authenticated else "api",
                updated_reason=updated_reason,
            )

            # 创建审计日志
            DecisionModelParamAuditLogModel.objects.create(
                param_key=param_key,
                old_value=old_value,
                new_value=str(param_value),
                env=env,
                changed_by=request.user.username if hasattr(request, "user") and request.user.is_authenticated else "api",
                change_reason=updated_reason,
            )

            return Response({
                "success": True,
                "data": {
                    "param_key": param_key,
                    "old_value": old_value,
                    "new_value": str(param_value),
                    "env": env,
                    "version": new_version,
                },
            })

        except Exception as e:
            logger.error(f"Failed to update model param: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
