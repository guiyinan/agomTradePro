"""Session and CSRF protected controls for the existing SZSE calendar chain."""

from datetime import datetime
from typing import cast
from uuid import UUID

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.data_center.calendar_renewal_composition import issue_renewal, revoke_renewal
from apps.data_center.interface.calendar_publication_api_views import _CalendarJsonAPIView
from apps.data_center.interface.calendar_publication_serializers import (
    _ExactStringField,
    _StrictSerializer,
    _UtcDateTimeField,
)


class _GrantInput(_StrictSerializer):
    dataset_key = _ExactStringField(max_length=160)
    expires_at = _UtcDateTimeField()


class CalendarRenewalGrantView(_CalendarJsonAPIView):
    """Delegate the signed-in owner's bounded SZSE publication authority."""

    def post(self, request: Request) -> Response:
        """Create a disabled schedule bound to the verified current head."""
        data = _GrantInput(data=request.data)
        data.is_valid(raise_exception=True)
        grant = issue_renewal(
            request,
            cast(str, data.validated_data["dataset_key"]),
            cast(datetime, data.validated_data["expires_at"]),
        )
        return Response(
            {"grant_id": str(grant), "schedule_enabled": False}, status=status.HTTP_201_CREATED
        )


class CalendarRenewalRevokeView(_CalendarJsonAPIView):
    """Revoke an exact delegation using the original owner's session."""

    def post(self, request: Request, grant_id: UUID) -> Response:
        """Block subsequent deliveries and disable the associated schedule."""
        if request.data != {}:
            raise serializers.ValidationError("Revocation accepts an empty object")
        revoke_renewal(request, grant_id)
        return Response({"grant_id": str(grant_id), "revoked": True})
