"""Governed API views for Audit threshold-validation workflows."""

from __future__ import annotations

import logging
from datetime import date
from typing import TypedDict, cast

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.application.interface_services import (
    preview_threshold_validation,
    run_threshold_validation,
)

from .serializers import (
    AuditValidationRequestSerializer,
    ThresholdValidationReportSerializer,
)

logger = logging.getLogger(__name__)


class _ValidationRequest(TypedDict):
    """Validated date range accepted by both validation endpoints."""

    start_date: date
    end_date: date


def _validation_request(request: Request) -> _ValidationRequest:
    """Validate and narrow one threshold-validation HTTP request."""

    serializer = AuditValidationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return cast(_ValidationRequest, serializer.validated_data)


class PreviewValidationView(APIView):
    """Return validation targets and impact without executing the workflow."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        """Return the governed read/write impact without executing validation."""

        payload = _validation_request(request)
        preview = preview_threshold_validation(
            start_date=payload["start_date"],
            end_date=payload["end_date"],
        )
        return Response({"success": True, "preview": preview})


class RunValidationView(APIView):
    """Run and persist one threshold-validation workflow."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        """Execute and serialize one governed threshold-validation run."""

        payload = _validation_request(request)
        response = run_threshold_validation(
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            use_shadow_mode=False,
        )
        if not response.success:
            return Response(
                {"success": False, "error": response.error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        report = response.validation_report
        report_data = None
        if report is not None:
            report_data = ThresholdValidationReportSerializer(
                {
                    "validation_run_id": report.validation_run_id,
                    "run_date": report.run_date,
                    "evaluation_period_start": report.evaluation_period_start,
                    "evaluation_period_end": report.evaluation_period_end,
                    "total_indicators": report.total_indicators,
                    "approved_indicators": report.approved_indicators,
                    "rejected_indicators": report.rejected_indicators,
                    "pending_indicators": report.pending_indicators,
                    "indicator_reports": report.indicator_reports,
                    "overall_recommendation": report.overall_recommendation,
                    "status": report.status.value,
                }
            ).data
        return Response(
            {
                "success": True,
                "validation_run_id": response.validation_run_id,
                "report": report_data,
            }
        )
