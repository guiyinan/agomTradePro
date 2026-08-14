"""Workspace execution API views."""

import logging
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.workspace_services import (
    build_recommendation_risk_checks,
    create_legacy_approval,
    create_unified_approval,
    get_aggregated_workspace_payload,
    get_approval_request,
    get_legacy_recommendation,
    get_related_candidate_ids,
    get_transition_plan,
    get_unified_recommendation,
    has_pending_request,
    save_transition_plan,
    update_approval_request_status,
)
from ..domain.exceptions import LegacyTransitionPlanWriteDisabledError
from ..domain.valuation_entities import ApprovalStatus, ExecutionApprovalRequest
from ..domain.valuation_services import ExecutionApprovalService
from ..domain.workflow_services import ApprovalStatusStateMachine
from .workspace_api_support import (
    _build_plan_risk_checks,
    _build_transition_plan_for_account,
    _create_approval_from_plan,
    _decimal,
    _regime_context,
    _serialize_transition_plan,
    _truthy,
    _update_transition_plan_from_payload,
)

logger = logging.getLogger(__name__)


def _request_payload(request: Request) -> dict[str, Any]:
    """Normalize a DRF request body to a string-key mapping."""

    raw_payload = request.data
    if not isinstance(raw_payload, Mapping):
        return {}
    return {str(key): value for key, value in raw_payload.items()}


def _optional_text(value: Any) -> str | None:
    """Normalize an optional request field to stripped text."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _string_list(value: Any, *, field_name: str) -> list[str] | None:
    """Validate an optional list of non-empty string identifiers."""

    if value in (None, ""):
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name} must be a list of non-empty strings")
        normalized.append(item.strip())
    return normalized


class AggregatedWorkspaceView(APIView):
    """GET /api/decision/workspace/aggregated/"""

    def get(self, request: Request) -> Response:
        account_id = _optional_text(request.query_params.get("account_id"))
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

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        account_id = _optional_text(payload.get("account_id")) or "default"

        try:
            recommendation_ids = _string_list(
                payload.get("recommendation_ids"),
                field_name="recommendation_ids",
            )
            plan = _build_transition_plan_for_account(
                account_id=account_id,
                recommendation_ids=recommendation_ids,
                persist=True,
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as exc:
            logger.error(f"Failed to generate transition plan: {exc}", exc_info=True)
            return Response(
                {"success": False, "error": "生成交易计划失败"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {"success": True, "data": _serialize_transition_plan(plan)},
            status=status.HTTP_201_CREATED,
        )


class TransitionPlanDetailView(APIView):
    """GET /api/decision/workspace/plans/<str:plan_id>/"""

    def get(self, request: Request, plan_id: str) -> Response:
        plan = get_transition_plan(plan_id)
        if plan is None:
            return Response(
                {"success": False, "error": "Transition plan not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": _serialize_transition_plan(plan)})


class TransitionPlanUpdateView(APIView):
    """POST /api/decision/workspace/plans/<str:plan_id>/update/"""

    def post(self, request: Request, plan_id: str) -> Response:
        plan = get_transition_plan(plan_id)
        if plan is None:
            return Response(
                {"success": False, "error": "Transition plan not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            updated_plan = _update_transition_plan_from_payload(
                plan,
                _request_payload(request),
            )
            updated_plan = save_transition_plan(updated_plan)
        except Exception as exc:
            logger.error(f"Failed to update transition plan {plan_id}: {exc}", exc_info=True)
            return Response(
                {"success": False, "error": "更新交易计划失败"}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response({"success": True, "data": _serialize_transition_plan(updated_plan)})


class ExecutionPreviewView(APIView):
    """POST /api/decision/execute/preview/"""

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        plan_id = _optional_text(payload.get("plan_id"))
        recommendation_id = _optional_text(payload.get("recommendation_id"))
        create_request = _truthy(payload.get("create_request"))
        account_id = _optional_text(payload.get("account_id")) or "default"
        market_price = _decimal(payload.get("market_price"))

        if plan_id:
            plan = get_transition_plan(plan_id)
            if plan is None:
                return Response(
                    {"success": False, "error": "Transition plan not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

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

            plan_request_id: str | None = None
            if create_request:
                regime_source = str(_regime_context()["source"])
                try:
                    approval_request = _create_approval_from_plan(
                        plan=plan,
                        account_id=account_id,
                        risk_checks=risk_checks,
                        regime_source=regime_source,
                        market_price=market_price,
                    )
                except ValueError as exc:
                    return Response(
                        {"success": False, "error": str(exc)}, status=status.HTTP_409_CONFLICT
                    )
                plan_request_id = approval_request.request_id

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": plan_request_id,
                        "plan_id": plan.plan_id,
                        "recommendation_type": "plan",
                        "preview": {
                            "orders_count": len(plan.orders),
                            "active_orders_count": len(
                                [order for order in plan.orders if order.action != "HOLD"]
                            ),
                            "summary": plan.summary,
                            "risk_contract": plan.risk_contract,
                        },
                        "risk_checks": risk_checks,
                    },
                },
                status=status.HTTP_201_CREATED if create_request else status.HTTP_200_OK,
            )

        if not recommendation_id:
            return Response(
                {"success": False, "error": "plan_id or recommendation_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 优先查找 UnifiedRecommendation（M2 融合推荐）
        uni_rec = get_unified_recommendation(recommendation_id)
        if uni_rec:
            risk_checks = build_recommendation_risk_checks(uni_rec, market_price)
            unified_request_id: str | None = None
            regime_source = str(_regime_context()["source"])
            if create_request:
                if has_pending_request(account_id, uni_rec.security_code, uni_rec.side):
                    return Response(
                        {
                            "success": False,
                            "error": "Pending request already exists for this account/security/side",
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                approval_request = create_unified_approval(
                    uni_rec,
                    account_id=account_id,
                    risk_checks=risk_checks,
                    regime_source=regime_source,
                    market_price=market_price,
                )
                unified_request_id = approval_request.request_id

            return Response(
                {
                    "success": True,
                    "data": {
                        "request_id": unified_request_id,
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
            return Response(
                {"success": False, "error": "Recommendation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        risk_checks = build_recommendation_risk_checks(recommendation, market_price)
        regime_source = str(_regime_context()["source"])
        legacy_request_id: str | None = None
        if create_request:
            if has_pending_request(account_id, recommendation.security_code, recommendation.side):
                return Response(
                    {
                        "success": False,
                        "error": "Pending request already exists for this account/security/side",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            approval_request = create_legacy_approval(
                recommendation,
                account_id=account_id,
                risk_checks=risk_checks,
                regime_source=regime_source,
                market_price=market_price,
            )
            legacy_request_id = approval_request.request_id

        return Response(
            {
                "success": True,
                "data": {
                    "request_id": legacy_request_id,
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


class ExecutionApproveView(APIView):
    """POST /api/decision/execute/approve/"""

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        request_id = _optional_text(payload.get("approval_request_id"))
        reviewer_comments = str(payload.get("reviewer_comments", ""))
        market_price = _decimal(payload.get("market_price"))

        if not request_id:
            return Response(
                {"success": False, "error": "approval_request_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response(
                {"success": False, "error": "Approval request not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        can_approve, reason = ExecutionApprovalService().can_approve(
            approval_request,
            market_price or approval_request.market_price_at_review or Decimal("0"),
        )
        if not can_approve:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        try:
            updated = update_approval_request_status(
                request_id=request_id,
                approval_status=ApprovalStatus.APPROVED,
                reviewer_comments=reviewer_comments,
            )
        except LegacyTransitionPlanWriteDisabledError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        # 发布决策批准事件（触发 Candidate 状态同步）
        if updated is not None:
            self._publish_decision_approved_event(updated)

        return Response(
            {"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}}
        )

    def _publish_decision_approved_event(
        self,
        approval_request: ExecutionApprovalRequest,
    ) -> None:
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
                logger.info(
                    f"Published DECISION_APPROVED event for request {approval_request.request_id}"
                )
        except Exception as exc:
            logger.error(
                "Failed to publish DECISION_APPROVED event: %s",
                exc,
                exc_info=True,
            )


class ExecutionRejectView(APIView):
    """POST /api/decision/execute/reject/"""

    def post(self, request: Request) -> Response:
        payload = _request_payload(request)
        request_id = _optional_text(payload.get("approval_request_id"))
        reviewer_comments = str(payload.get("reviewer_comments", ""))

        if not request_id:
            return Response(
                {"success": False, "error": "approval_request_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response(
                {"success": False, "error": "Approval request not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        can_transition, reason = ApprovalStatusStateMachine.validate_transition(
            approval_request.approval_status,
            ApprovalStatus.REJECTED,
        )
        if not can_transition:
            return Response({"success": False, "error": reason}, status=status.HTTP_400_BAD_REQUEST)

        # 更新状态（会同步到 UnifiedRecommendation 和 InvestmentRecommendation）
        try:
            updated = update_approval_request_status(
                request_id=request_id,
                approval_status=ApprovalStatus.REJECTED,
                reviewer_comments=reviewer_comments,
            )
        except LegacyTransitionPlanWriteDisabledError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        # 发布决策拒绝事件
        if updated is not None:
            self._publish_decision_rejected_event(updated)

        return Response(
            {"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}}
        )

    def _publish_decision_rejected_event(
        self,
        approval_request: ExecutionApprovalRequest,
    ) -> None:
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
            logger.info(
                f"Published DECISION_REJECTED event for request {approval_request.request_id}"
            )
        except Exception as exc:
            logger.error(
                "Failed to publish DECISION_REJECTED event: %s",
                exc,
                exc_info=True,
            )


class ExecutionRequestDetailView(APIView):
    """GET /api/decision/execute/{request_id}/"""

    def get(self, request: Request, request_id: str) -> Response:
        approval_request = get_approval_request(request_id)
        if approval_request is None:
            return Response(
                {"success": False, "error": "Approval request not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "data": approval_request.to_dict()})
