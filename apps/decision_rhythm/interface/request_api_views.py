"""Decision request query API views for decision rhythm."""

from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from ..application.query_workflows import (
    GetDecisionRequestRequest,
    GetDecisionRequestStatisticsRequest,
    ListDecisionRequestsRequest,
)
from .api_response_utils import bad_request_response, internal_error_response
from .dependencies import (
    build_get_decision_request_statistics_use_case,
    build_get_decision_request_use_case,
    build_list_decision_requests_use_case,
)
from .serializers import (
    DecisionRequestListQuerySerializer,
    DecisionRequestSerializer,
    DecisionRequestStatisticsQuerySerializer,
)


class DecisionRequestViewSet(viewsets.ViewSet):
    """Decision request read endpoints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.list_use_case = build_list_decision_requests_use_case()
        self.get_request_use_case = build_get_decision_request_use_case()
        self.statistics_use_case = build_get_decision_request_statistics_use_case()

    def list(self, request) -> Response:
        """GET /api/decision-rhythm/requests/"""
        try:
            serializer = DecisionRequestListQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            requests = self.list_use_case.execute(
                ListDecisionRequestsRequest(
                    days=data.get("days", 30),
                    asset_code=data.get("asset_code") or None,
                )
            )
            response_serializer = DecisionRequestSerializer(requests, many=True)
            return Response(
                {
                    "success": True,
                    "count": len(requests),
                    "results": response_serializer.data,
                }
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to list requests", exc)

    def retrieve(self, request, pk=None) -> Response:
        """GET /api/decision-rhythm/requests/{request_id}/"""
        try:
            decision_request = self.get_request_use_case.execute(
                GetDecisionRequestRequest(request_id=pk or "")
            )
            if decision_request is None:
                return Response(
                    {"success": False, "error": "Request not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = DecisionRequestSerializer(decision_request)
            return Response({"success": True, "result": serializer.data})
        except Exception as exc:
            return internal_error_response("Failed to retrieve request", exc)

    @action(detail=False, methods=["GET"], url_path="statistics")
    def statistics(self, request) -> Response:
        """GET /api/decision-rhythm/requests/statistics/"""
        try:
            serializer = DecisionRequestStatisticsQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            stats = self.statistics_use_case.execute(
                GetDecisionRequestStatisticsRequest(days=data.get("days", 30))
            )
            return Response({"success": True, "result": stats})
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to get statistics", exc)
