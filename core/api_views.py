"""Core read-only API views."""

from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.application.config_center import (
    build_config_center_snapshot,
    list_config_capabilities,
)


class ConfigCenterSnapshotView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response({
            "success": True,
            "data": build_config_center_snapshot(request.user),
        })


class ConfigCapabilitiesView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response({
            "success": True,
            "data": list_config_capabilities(),
        })
