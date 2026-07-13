"""Governed API views for Audit attribution-report generation."""

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.application.interface_services import (
    generate_attribution_report_payload,
    preview_attribution_report_generation,
)

from .serializers import (
    AttributionReportSerializer,
    GenerateAttributionReportRequestSerializer,
)


def _validated_report_request(request: Request) -> dict[str, Any]:
    serializer = GenerateAttributionReportRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _preview_or_response(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, Response | None]:
    try:
        return preview_attribution_report_generation(**payload), None
    except LookupError as exc:
        return None, Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return None, Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PreviewAttributionReportView(APIView):
    """Preview generation targets and side effects without running analysis."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        payload = _validated_report_request(request)
        preview, error_response = _preview_or_response(payload)
        if error_response is not None:
            return error_response
        return Response({"success": True, "preview": preview})


class GenerateAttributionReportView(APIView):
    """Generate and persist an attribution report for one completed backtest."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        payload = _validated_report_request(request)
        _, error_response = _preview_or_response(payload)
        if error_response is not None:
            return error_response

        result = generate_attribution_report_payload(payload["backtest_id"])
        if not result["success"]:
            return Response({"error": result["error"]}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AttributionReportSerializer(result["report"])
        return Response(serializer.data, status=status.HTTP_201_CREATED)
