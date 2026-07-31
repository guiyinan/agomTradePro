"""Read-only MCP access verification API."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.application import interface_services as account_interface_services
from apps.ai_capability.application import interface_services

from .serializers import MCPAccessVerificationSerializer


class MCPAccessVerificationView(APIView):
    """Verify the current user's effective MCP access without invoking AI."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return bounded token, routing, and catalog readiness checks."""

        user_id = request.user.pk
        if user_id is None:
            return Response({"error": "authenticated_user_required"}, status=403)
        base_url = account_interface_services.resolve_mcp_public_base_url(
            request.build_absolute_uri("/").rstrip("/")
        )
        readiness = interface_services.inspect_mcp_access_readiness()
        self_service = account_interface_services.build_self_mcp_api_payload(
            user_id,
            base_url=base_url,
            routing_available=bool(readiness["routing_available"]),
            catalog_available=bool(readiness["catalog_available"]),
        )
        payload = account_interface_services.build_mcp_access_verification_payload(
            self_service,
            routing_available=bool(readiness["routing_available"]),
            catalog_available=bool(readiness["catalog_available"]),
        )
        return Response(MCPAccessVerificationSerializer(payload).data)
