"""Decision rhythm submit workflow orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from django.utils import timezone

from apps.alpha_trigger.domain.entities import CandidateStatus

from ..domain.entities import (
    DecisionFeatureSnapshot,
    DecisionRequest,
    RecommendationStatus,
    UnifiedRecommendation,
)
from .use_cases import SubmitBatchRequestRequest, SubmitDecisionRequestRequest

logger = logging.getLogger(__name__)


@dataclass
class SubmitDecisionWorkflowRequest:
    """Application-level request for the legacy submit endpoint workflow."""

    submit_request: SubmitDecisionRequestRequest
    account_id: str = "default"


@dataclass
class SubmitDecisionWorkflowResponse:
    """Application-level response for the legacy submit endpoint workflow."""

    success: bool
    decision_request: DecisionRequest | None = None
    recommendation_id: str | None = None
    deduplicated: bool = False
    message: str | None = None
    error: str | None = None


@dataclass
class SubmitBatchWorkflowRequest:
    """Application-level request for the batch submit endpoint workflow."""

    batch_request: SubmitBatchRequestRequest


@dataclass
class SubmitBatchWorkflowResponse:
    """Application-level response for the batch submit endpoint workflow."""

    success: bool
    decision_requests: list[DecisionRequest]
    summary: dict[str, Any]
    error: str | None = None


class SubmitDecisionWorkflowUseCase:
    """Orchestrate submit, persistence, legacy recommendation sync, and candidate compaction."""

    def __init__(
        self,
        *,
        submit_use_case,
        request_repo,
        recommendation_repo,
        candidate_repo=None,
    ):
        self.submit_use_case = submit_use_case
        self.request_repo = request_repo
        self.recommendation_repo = recommendation_repo
        self.candidate_repo = candidate_repo

    def execute(
        self,
        request: SubmitDecisionWorkflowRequest,
    ) -> SubmitDecisionWorkflowResponse:
        """Execute the legacy submit workflow and persist all side effects."""
        candidate_id = request.submit_request.candidate_id or ""
        if candidate_id:
            open_by_candidate = self.request_repo.get_open_by_candidate_id(candidate_id)
            if open_by_candidate:
                return SubmitDecisionWorkflowResponse(
                    success=True,
                    decision_request=open_by_candidate,
                    deduplicated=True,
                    message="该候选已有待执行请求，已复用",
                )

        open_by_asset = self.request_repo.get_open_by_asset_code(
            request.submit_request.asset_code
        )
        if open_by_asset:
            return SubmitDecisionWorkflowResponse(
                success=True,
                decision_request=open_by_asset,
                deduplicated=True,
                message="该证券已有待执行请求，已复用",
            )

        submit_response = self.submit_use_case.execute(request.submit_request)
        if (
            not submit_response.success
            or submit_response.response is None
            or submit_response.decision_request is None
        ):
            return SubmitDecisionWorkflowResponse(
                success=False,
                error=submit_response.error or "Submit decision request failed",
            )

        self.request_repo.save_request(submit_response.decision_request)
        self.request_repo.save_response(
            submit_response.response.request_id,
            submit_response.response,
        )

        recommendation_id = self._ensure_legacy_recommendation(
            request=request,
            decision_request=submit_response.decision_request,
        )

        if submit_response.response.approved:
            self._compact_candidate(submit_response.decision_request)

        return SubmitDecisionWorkflowResponse(
            success=True,
            decision_request=submit_response.decision_request,
            recommendation_id=recommendation_id,
        )

    def _ensure_legacy_recommendation(
        self,
        *,
        request: SubmitDecisionWorkflowRequest,
        decision_request,
    ) -> str | None:
        """Create or reuse a minimal unified recommendation for legacy submit flows."""
        try:
            existing = self.recommendation_repo.get_active_by_key(
                account_id=request.account_id,
                security_code=request.submit_request.asset_code,
                side=request.submit_request.direction,
            )
            candidate_id = request.submit_request.candidate_id
            if existing:
                if candidate_id:
                    updated = self.recommendation_repo.append_source_candidate_ids(
                        existing.recommendation_id,
                        [candidate_id],
                    )
                    if updated:
                        return updated.recommendation_id
                return existing.recommendation_id

            snapshot = DecisionFeatureSnapshot(
                snapshot_id=f"fsn_legacy_{uuid4().hex[:12]}",
                security_code=request.submit_request.asset_code,
                snapshot_time=timezone.now(),
                regime="UNKNOWN",
                regime_confidence=0.0,
                policy_level="UNKNOWN",
                beta_gate_passed=True,
            )
            self.recommendation_repo.save_feature_snapshot(snapshot)

            recommendation = UnifiedRecommendation(
                recommendation_id=f"urec_legacy_{uuid4().hex[:12]}",
                account_id=request.account_id,
                security_code=request.submit_request.asset_code,
                side=request.submit_request.direction,
                regime="UNKNOWN",
                regime_confidence=0.0,
                policy_level="UNKNOWN",
                beta_gate_passed=True,
                composite_score=0.0,
                confidence=request.submit_request.expected_confidence or 0.5,
                reason_codes=(
                    [request.submit_request.reason]
                    if request.submit_request.reason
                    else ["legacy_submit"]
                ),
                human_rationale=(
                    f"Legacy submit: {request.submit_request.reason or 'N/A'}"
                ),
                fair_value=Decimal("0"),
                entry_price_low=Decimal("0"),
                entry_price_high=Decimal("0"),
                target_price_low=Decimal("0"),
                target_price_high=Decimal("0"),
                stop_loss_price=Decimal("0"),
                position_pct=0.0,
                suggested_quantity=request.submit_request.quantity or 0,
                max_capital=Decimal(str(request.submit_request.notional or 0)),
                source_signal_ids=[],
                source_candidate_ids=[candidate_id] if candidate_id else [],
                feature_snapshot_id=snapshot.snapshot_id,
                status=RecommendationStatus.NEW,
            )
            saved = self.recommendation_repo.save(recommendation)
            return saved.recommendation_id
        except Exception as exc:
            logger.warning(
                "Failed to create UnifiedRecommendation from legacy submit: %s",
                exc,
            )
            return None

    def _compact_candidate(self, decision_request) -> None:
        """Move the source candidate out of ACTIONABLE after successful submit approval."""
        if not self.candidate_repo or not decision_request.candidate_id:
            return
        try:
            self.candidate_repo.update_status(
                candidate_id=decision_request.candidate_id,
                status=CandidateStatus.CANDIDATE,
            )
            self.candidate_repo.update_execution_tracking(
                candidate_id=decision_request.candidate_id,
                decision_request_id=decision_request.request_id,
                execution_status="PENDING",
            )
        except Exception as exc:
            logger.warning("Failed to compact candidate status after submit: %s", exc)


class SubmitBatchWorkflowUseCase:
    """Orchestrate batch submit plus persistence outside the interface layer."""

    def __init__(self, *, submit_use_case, request_repo):
        self.submit_use_case = submit_use_case
        self.request_repo = request_repo

    def execute(
        self,
        request: SubmitBatchWorkflowRequest,
    ) -> SubmitBatchWorkflowResponse:
        """Execute the batch workflow and persist all successful results."""
        submit_response = self.submit_use_case.execute(request.batch_request)
        if not submit_response.success:
            return SubmitBatchWorkflowResponse(
                success=False,
                decision_requests=[],
                summary={},
                error=submit_response.error or "Submit batch decision requests failed",
            )

        for decision_request, response in zip(
            submit_response.decision_requests,
            submit_response.responses,
            strict=False,
        ):
            self.request_repo.save_request(decision_request)
            self.request_repo.save_response(response.request_id, response)

        return SubmitBatchWorkflowResponse(
            success=True,
            decision_requests=submit_response.decision_requests,
            summary=submit_response.summary,
        )
