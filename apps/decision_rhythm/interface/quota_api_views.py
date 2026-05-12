"""Quota query and management API views for decision rhythm."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from ..application.management_workflows import ResetQuotaByAccountRequest, TrendDataRequest
from ..application.query_workflows import (
    GetDecisionQuotaByPeriodRequest,
    ListDecisionQuotasRequest,
)
from ..domain.entities import QuotaPeriod
from .api_response_utils import bad_request_response, internal_error_response
from .dependencies import (
    build_get_decision_quota_by_period_use_case,
    build_get_trend_data_use_case,
    build_list_decision_quotas_use_case,
    build_reset_quota_by_account_use_case,
)
from .serializers import (
    DecisionQuotaByPeriodQuerySerializer,
    DecisionQuotaListQuerySerializer,
    DecisionQuotaSerializer,
    ResetQuotaRequestSerializer,
    TrendDataQuerySerializer,
)


class DecisionQuotaViewSet(viewsets.ViewSet):
    """Decision quota read endpoints."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.list_use_case = build_list_decision_quotas_use_case()
        self.get_by_period_use_case = build_get_decision_quota_by_period_use_case()

    def list(self, request) -> Response:
        """GET /api/decision-rhythm/quotas/"""
        try:
            serializer = DecisionQuotaListQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)

            data = serializer.validated_data
            period = data.get("period")
            quotas = self.list_use_case.execute(
                ListDecisionQuotasRequest(
                    period=QuotaPeriod(period) if period else None,
                    account_id=data.get("account_id"),
                )
            )

            response_serializer = DecisionQuotaSerializer(quotas, many=True)
            return Response(
                {
                    "success": True,
                    "count": len(quotas),
                    "results": response_serializer.data,
                }
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to list quotas", exc)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="period",
                type=OpenApiTypes.STR,
                enum=[qp.value for qp in QuotaPeriod],
                description="配额周期",
            ),
        ],
        responses={200: DecisionQuotaSerializer},
    )
    @action(detail=False, methods=["GET"], url_path="by-period")
    def by_period(self, request) -> Response:
        """GET /api/decision-rhythm/quotas/by-period/"""
        try:
            serializer = DecisionQuotaByPeriodQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            quota = self.get_by_period_use_case.execute(
                GetDecisionQuotaByPeriodRequest(
                    period=QuotaPeriod(data["period"]),
                    account_id=data.get("account_id", "default"),
                )
            )
            if quota is None:
                return Response(
                    {"success": False, "error": "Quota not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            response_serializer = DecisionQuotaSerializer(quota)
            return Response({"success": True, "result": response_serializer.data})
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except Exception as exc:
            return internal_error_response("Failed to get quota by period", exc)


class ResetQuotaView(APIView):
    """POST /api/decision-rhythm/reset-quota/"""

    @extend_schema(request=ResetQuotaRequestSerializer, responses={200: dict})
    def post(self, request) -> Response:
        """Reset one or all quotas for the selected account."""
        try:
            serializer = ResetQuotaRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            use_case = build_reset_quota_by_account_use_case()
            response = use_case.execute(
                ResetQuotaByAccountRequest(
                    account_id=str(data.get("account_id") or "default"),
                    period=(QuotaPeriod(data["period"]) if data.get("period") else None),
                )
            )
            if response.success:
                return Response({"success": True, "message": response.message})

            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except (TypeError, ValueError, KeyError) as exc:
            return bad_request_response(exc)
        except Exception as exc:
            return internal_error_response("Failed to reset quota", exc)


class TrendDataView(APIView):
    """GET /api/decision-rhythm/trend-data/"""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="days",
                type=OpenApiTypes.INT,
                description="天数 (7 或 30)",
                enum=[7, 30],
            ),
        ],
        responses={200: dict},
    )
    def get(self, request) -> Response:
        """Return quota usage trend data."""
        try:
            serializer = TrendDataQuerySerializer(data=request.query_params)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data

            use_case = build_get_trend_data_use_case()
            response = use_case.execute(
                TrendDataRequest(
                    days=int(data.get("days", 7)),
                    account_id=str(data.get("account_id") or "default"),
                )
            )
            if response.success and response.data is not None:
                return Response({"success": True, "data": response.data})

            return Response(
                {"success": False, "error": response.error or "Failed to get trend data"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DRFValidationError as exc:
            return bad_request_response(exc.detail)
        except (TypeError, ValueError) as exc:
            return bad_request_response(f"Invalid query params: {exc}")
        except Exception as exc:
            return internal_error_response("Failed to get trend data", exc)
