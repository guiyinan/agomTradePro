"""Governed API views for Audit threshold-level configuration."""

from typing import Any

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.application.interface_services import (
    preview_indicator_threshold_levels,
    update_indicator_threshold_levels,
)

from .serializers import AuditThresholdLevelsRequestSerializer


def _validated_threshold_request(request: Request) -> dict[str, Any]:
    serializer = AuditThresholdLevelsRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _preview_or_response(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, Response | None]:
    try:
        return preview_indicator_threshold_levels(**payload), None
    except LookupError as exc:
        return None, Response({"error": str(exc)}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return None, Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PreviewThresholdLevelsView(APIView):
    """Read current and proposed threshold levels without changing them."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        payload = _validated_threshold_request(request)
        preview, error_response = _preview_or_response(payload)
        if error_response is not None:
            return error_response
        return Response({"success": True, "preview": preview})


class UpdateThresholdLevelsView(APIView):
    """Apply a validated threshold-level change for one active indicator."""

    permission_classes = [IsAdminUser]

    def post(self, request: Request) -> Response:
        payload = _validated_threshold_request(request)
        preview, error_response = _preview_or_response(payload)
        if error_response is not None:
            return error_response
        updated = update_indicator_threshold_levels(**payload)
        if not updated:
            return Response(
                {"error": f"indicator {payload['indicator_code']} threshold config does not exist"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"success": True, "updated": preview})
