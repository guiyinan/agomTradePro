"""Core read-only API views."""

from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.application.config_center import (
    build_config_center_snapshot,
    list_config_capabilities,
)


class ConfigCenterSnapshotView(APIView):
    """Return the staff-only cross-App configuration snapshot."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        """Return the validated configuration snapshot."""

        return Response(
            {
                "success": True,
                "data": build_config_center_snapshot(request.user),
            }
        )


class ConfigCapabilitiesView(APIView):
    """Return the static staff-only configuration capability catalog."""

    permission_classes = [IsAdminUser]

    def get(self, request: Request) -> Response:
        """Return the configuration capability catalog."""

        return Response(
            {
                "success": True,
                "data": list_config_capabilities(),
            }
        )
