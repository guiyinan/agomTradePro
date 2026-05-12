"""Command and summary API views for decision rhythm."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.submit_workflows import (
    SubmitBatchWorkflowRequest,
    SubmitDecisionWorkflowRequest,
)
from ..application.use_cases import (
    GetRhythmSummaryRequest,
    SubmitBatchRequestRequest,
    SubmitDecisionRequestRequest,
)
from ..domain.entities import DecisionPriority, QuotaPeriod
from .api_response_utils import bad_request_response, internal_error_response
from .dependencies import (
    build_get_rhythm_summary_use_case,
    build_submit_batch_workflow_use_case,
    build_submit_decision_workflow_use_case,
)
from .serializers import (
    DecisionRequestSerializer,
    SubmitBatchRequestRequestSerializer,
    SubmitDecisionRequestRequestSerializer,
)


def build_submit_request(
    data: dict[str, Any],
    *,
    quota_period: QuotaPeriod,
) -> SubmitDecisionRequestRequest:
    """Convert serializer data into the application submit request DTO."""
    candidate_id = data.get("candidate_id", "") or ""
    return SubmitDecisionRequestRequest(
        asset_code=data["asset_code"],
        asset_class=data["asset_class"],
        direction=data["direction"],
        priority=DecisionPriority(data["priority"]),
        trigger_id=data.get("trigger_id"),
        candidate_id=candidate_id or None,
        reason=data.get("reason", ""),
        expected_confidence=data.get("expected_confidence", 0.0),
        quantity=data.get("quantity"),
        notional=data.get("notional"),
        quota_period=quota_period,
    )


class SubmitDecisionRequestView(APIView):
    """POST /api/decision-rhythm/submit/"""

    @extend_schema(
        request=SubmitDecisionRequestRequestSerializer,
        responses={200: DecisionRequestSerializer},
    )
    def post(self, request) -> Response:
        """Submit a single decision request."""
        try:
            serializer = SubmitDecisionRequestRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data
            quota_period = QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value))
            req = build_submit_request(data, quota_period=quota_period)

            workflow_use_case = build_submit_decision_workflow_use_case()
            response = workflow_use_case.execute(
                SubmitDecisionWorkflowRequest(
                    submit_request=req,
                    account_id=str(data.get("account_id") or "default"),
                )
            )
            if response.success and response.decision_request is not None:
                request_serializer = DecisionRequestSerializer(response.decision_request)
                payload = {
                    "success": True,
                    "result": request_serializer.data,
                    "recommendation_id": response.recommendation_id,
                }
                if response.deduplicated:
                    payload["deduplicated"] = True
                    payload["message"] = response.message
                return Response(payload)

            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except (TypeError, ValueError, KeyError) as exc:
            return bad_request_response(exc)
        except Exception as exc:
            return internal_error_response("Failed to submit decision request", exc)


class SubmitBatchRequestView(APIView):
    """POST /api/decision-rhythm/submit-batch/"""

    @extend_schema(request=SubmitBatchRequestRequestSerializer, responses={200: dict})
    def post(self, request) -> Response:
        """Submit a batch of decision requests."""
        try:
            serializer = SubmitBatchRequestRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data
            quota_period = QuotaPeriod(data.get("quota_period", QuotaPeriod.WEEKLY.value))
            requests = [
                build_submit_request(req_data, quota_period=quota_period)
                for req_data in data["requests"]
            ]
            batch_req = SubmitBatchRequestRequest(
                requests=requests,
                quota_period=quota_period,
            )

            workflow_use_case = build_submit_batch_workflow_use_case()
            response = workflow_use_case.execute(
                SubmitBatchWorkflowRequest(batch_request=batch_req)
            )
            if response.success:
                request_serializer = DecisionRequestSerializer(
                    response.decision_requests,
                    many=True,
                )
                return Response(
                    {
                        "success": True,
                        "requests": request_serializer.data,
                        "summary": response.summary,
                    }
                )

            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except (TypeError, ValueError, KeyError) as exc:
            return bad_request_response(exc)
        except Exception as exc:
            return internal_error_response("Failed to submit batch decision requests", exc)


class GetRhythmSummaryView(APIView):
    """GET /api/decision-rhythm/summary/"""

    @extend_schema(responses={200: dict})
    def get(self, request) -> Response:
        """Return rhythm summary."""
        try:
            use_case = build_get_rhythm_summary_use_case()
            response = use_case.execute(GetRhythmSummaryRequest())
            if response.success:
                return Response({"success": True, "result": response.summary})

            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            return internal_error_response("Failed to get rhythm summary", exc)
