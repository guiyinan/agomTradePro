"""Decision Rhythm API views for valuation pricing and execution approval workflow."""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.regime.application.current_regime import resolve_current_regime

from ..domain.entities import ApprovalStatus, QuotaPeriod, create_execution_approval_request
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
    QuotaRepository,
    ValuationSnapshotRepository,
)

logger = logging.getLogger(__name__)


def _decimal(value: Any, *, default: Optional[Decimal] = None) -> Optional[Decimal]:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _regime_context() -> Dict[str, Any]:
    try:
        current = resolve_current_regime() or {}
        return {
            "current_regime": current.get("regime", "UNKNOWN"),
            "confidence": current.get("confidence", 0.0),
            "source": current.get("source", "V2_CALCULATION"),
        }
    except Exception:
        return {
            "current_regime": "UNKNOWN",
            "confidence": 0.0,
            "source": "V2_CALCULATION",
        }


def _risk_checks(recommendation, market_price: Optional[Decimal]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}

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


class ExecutionPreviewView(APIView):
    """POST /api/decision/execute/preview/"""

    def post(self, request) -> Response:
        recommendation_id = (request.data or {}).get("recommendation_id")
        account_id = (request.data or {}).get("account_id") or "default"
        market_price = _decimal((request.data or {}).get("market_price"))

        if not recommendation_id:
            return Response({"success": False, "error": "recommendation_id is required"}, status=status.HTTP_400_BAD_REQUEST)

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

        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.APPROVED,
            reviewer_comments=reviewer_comments,
        )
        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})


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

        updated = repo.update_status(
            request_id=request_id,
            approval_status=ApprovalStatus.REJECTED,
            reviewer_comments=reviewer_comments,
        )
        return Response({"success": True, "data": updated.to_dict() if updated else {"request_id": request_id}})


class ExecutionRequestDetailView(APIView):
    """GET /api/decision/execute/{request_id}/"""

    def get(self, request, request_id: str) -> Response:
        approval_request = ExecutionApprovalRequestRepository().get_by_id(request_id)
        if approval_request is None:
            return Response({"success": False, "error": "Approval request not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "data": approval_request.to_dict()})
