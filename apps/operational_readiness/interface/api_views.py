"""Administrator API views for operational release readiness."""

from __future__ import annotations

from rest_framework.permissions import BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.operational_readiness.composition import make_get_release_identity_use_case


class ReleaseIdentityView(APIView):
    """Return the verified Git and image identity of the running release."""

    permission_classes: list[type[BasePermission]] = [IsAdminUser]

    def get(self, request: Request) -> Response:
        """Return fail-closed deployment provenance for an administrator."""

        del request
        return Response(
            {
                "success": True,
                "data": make_get_release_identity_use_case().execute(),
            }
        )
