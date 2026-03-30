"""Decision Rhythm API views for valuation pricing and execution approval workflow."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_provider.application.chat_completion import AIClientFactory, generate_chat_completion
from apps.pulse.application.use_cases import GetLatestPulseUseCase
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
    return {
        UserDecisionAction.PENDING.value: "待决策",
        UserDecisionAction.WATCHING.value: "观察中",
        UserDecisionAction.ADOPTED.value: "已采纳",
        UserDecisionAction.IGNORED.value: "已忽略",
    }.get(value, value)


def _risk_checks(recommendation, market_price: Decimal | None) -> dict[str, Any]:
    return build_recommendation_risk_checks(recommendation, market_price)


def _serialize_transition_plan(plan: PortfolioTransitionPlan) -> dict[str, Any]:
    return serialize_transition_plan_payload(plan)


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


class ValuationSnapshotDetailView(APIView):
    """GET /api/valuation/snapshot/{snapshot_id}/"""

    def get(self, request, snapshot_id: str) -> Response:
        snapshot = get_valuation_snapshot(snapshot_id)
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

        snapshot = recalculate_valuation_snapshot(
            security_code=security_code,
            valuation_method=valuation_method,
            fair_value=fair_value,
            current_price=current_price,
            input_parameters=(request.data or {}).get("input_parameters") or {"source": "api_recalculate"},
        )
        return Response({"success": True, "data": snapshot.to_dict()}, status=status.HTTP_201_CREATED)


class AggregatedWorkspaceView(APIView):
    """GET /api/decision/workspace/aggregated/"""

    def get(self, request) -> Response:
        account_id = request.query_params.get("account_id")
        payload = get_aggregated_workspace_payload(account_id)

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
        plan = get_transition_plan(plan_id)
        if plan is None:
            return Response({"success": False, "error": "Transition plan not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": _serialize_transition_plan(plan)})


class TransitionPlanUpdateView(APIView):
    """POST /api/decision/workspace/plans/<str:plan_id>/update/"""

    def post(self, request, plan_id: str) -> Response:
        plan = get_transition_plan(plan_id)
        if plan is None:
            return Response({"success": False, "error": "Transition plan not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            updated_plan = _update_transition_plan_from_payload(plan, request.data or {})
            updated_plan = save_transition_plan(updated_plan)
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

        ai_response = generate_chat_completion(
            messages=messages,
            temperature=0.2,
            max_tokens=500,
            factory_class=AIClientFactory,
        )
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
        create_request = _truthy((request.data or {}).get("create_request"))
        account_id = (request.data or {}).get("account_id") or "default"
        market_price = _decimal((request.data or {}).get("market_price"))

        if plan_id:
            plan = get_transition_plan(plan_id)
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

            request_id: str | None = None
            if create_request:
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
                request_id = approval_request.request_id

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": request_id,
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
                status=status.HTTP_201_CREATED if create_request else status.HTTP_200_OK,
            )

        if not recommendation_id:
            return Response({"success": False, "error": "plan_id or recommendation_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        # 优先查找 UnifiedRecommendation（M2 融合推荐）
        uni_rec = get_unified_recommendation(recommendation_id)
        if uni_rec:
            risk_checks = self._risk_checks_from_unified(uni_rec, market_price)
            request_id: str | None = None
            regime_source = _regime_context()["source"]
            if create_request:
                if has_pending_request(account_id, uni_rec.security_code, uni_rec.side):
                    return Response(
                        {"success": False, "error": "Pending request already exists for this account/security/side"},
                        status=status.HTTP_409_CONFLICT,
                    )

                approval_request = self._create_approval_from_unified(
                    uni_rec=uni_rec,
                    account_id=account_id,
                    risk_checks=risk_checks,
                    regime_source=regime_source,
                    market_price=market_price,
                )
                request_id = approval_request.request_id

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": request_id,
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
                status=status.HTTP_201_CREATED if create_request else status.HTTP_200_OK,
            )

        # 回退到旧版 InvestmentRecommendation
        recommendation = get_legacy_recommendation(recommendation_id)
        if recommendation is None:
            return Response({"success": False, "error": "Recommendation not found"}, status=status.HTTP_404_NOT_FOUND)

        risk_checks = _risk_checks(recommendation, market_price)
        regime_source = _regime_context()["source"]
        request_id: str | None = None
        if create_request:
            if has_pending_request(account_id, recommendation.security_code, recommendation.side):
                return Response(
                    {"success": False, "error": "Pending request already exists for this account/security/side"},
                    status=status.HTTP_409_CONFLICT,
                )

            approval_request = create_legacy_approval(
                recommendation,
                account_id=account_id,
                risk_checks=risk_checks,
                regime_source=regime_source,
                market_price=market_price,
            )
            request_id = approval_request.request_id

        return Response(
            {
                "success": True,
                "data": {
                    "request_id": request_id,
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
            status=status.HTTP_201_CREATED if create_request else status.HTTP_200_OK,
        )

    def _risk_checks_from_unified(self, uni_rec, market_price) -> dict[str, Any]:
        """从 UnifiedRecommendation 构建风控检查结果"""
        return build_recommendation_risk_checks(uni_rec, market_price)

    def _create_approval_from_unified(
        self, uni_rec, account_id, risk_checks, regime_source, market_price
    ):
        """从 UnifiedRecommendation 创建审批请求"""
        return create_unified_approval(
            uni_rec,
            account_id=account_id,
            risk_checks=risk_checks,
            regime_source=regime_source,
            market_price=market_price,
        )


class ExecutionApproveView(APIView):
    """POST /api/decision/execute/approve/"""

    def post(self, request) -> Response:
        request_id = (request.data or {}).get("approval_request_id")
        reviewer_comments = (request.data or {}).get("reviewer_comments", "")
        market_price = _decimal((request.data or {}).get("market_price"))

        if not request_id:
            return Response({"success": False, "error": "approval_request_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_approve, reason = ExecutionApprovalService().can_approve(
            approval_request,
            market_price or approval_request.market_price_at_review or Decimal("0"),
        )
        if not can_approve:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        updated = update_approval_request_status(
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

            candidate_ids = get_related_candidate_ids(approval_request.request_id)

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

        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)

        can_transition, reason = ApprovalStatusStateMachine.validate_transition(
            approval_request.approval_status,
            ApprovalStatus.REJECTED,
        )
        if not can_transition:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        updated = update_approval_request_status(
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

            candidate_ids = get_related_candidate_ids(approval_request.request_id)

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
        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": approval_request.to_dict()})


# ============================================================================
# 统一推荐 API 端点（Top-down + Bottom-up 融合）
# ============================================================================

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
            recommendations, total_count = list_workspace_recommendations(
                account_id=account_id,
                status=status_filter,
                user_action=user_action_filter,
                security_code=security_code_filter,
                include_ignored=include_ignored,
                recommendation_id=recommendation_id,
                page=page,
                page_size=page_size,
            )

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

        user_action = self.ACTION_MAPPING[action]
        dto = update_workspace_recommendation_action(
            recommendation_id=recommendation_id,
            action=user_action,
            note=note,
            account_id=account_id,
        )
        if dto is None:
            return Response(
                {"success": False, "error": "Recommendation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "success": True,
                "data": {
                    "recommendation": dto.to_dict(),
                    "message": f"已更新为{_user_action_label(dto.user_action)}",
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
        # 解析请求
        dto = RefreshRecommendationsRequestDTO.from_dict(request.data or {})

        try:
            response_dto = refresh_workspace_recommendations(dto)

            return Response({
                "success": response_dto.status != "FAILED",
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
            conflicts = list_workspace_conflicts(account_id)

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
            return Response({
                "success": True,
                "data": get_model_params_payload(env),
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
            payload = update_model_param_payload(
                param_key=param_key,
                param_value=str(param_value),
                param_type=param_type,
                env=env,
                updated_by=request.user.username if hasattr(request, "user") and request.user.is_authenticated else "api",
                updated_reason=updated_reason,
            )
            return Response({
                "success": True,
                "data": payload,
            })

        except Exception as e:
            logger.error(f"Failed to update model param: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
