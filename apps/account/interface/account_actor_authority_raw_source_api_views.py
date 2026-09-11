"""CSRF-protected HTTP entry point for authenticated Account raw attestations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.account_actor_authority_raw_source_publisher_composition import (
    build_account_actor_authority_raw_source_publisher,
)
from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_actor_authority_raw_source_publisher_v3 import (
    PublishAccountActorAuthorityRawSourceV3Command,
)


class AccountActorAuthorityRawSourcePublishRequestSerializer(
    serializers.Serializer[dict[str, object]]
):
    """Accept an explicit empty JSON object and reject all client authority fields."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Validate that the request body is an empty string-keyed object."""

        if isinstance(data, Mapping):
            if any(type(key) is not str for key in data):
                raise serializers.ValidationError(
                    {"non_field_errors": ["Object keys must be strings."]}
                )
            if data:
                raise serializers.ValidationError(
                    {"non_field_errors": ["This endpoint accepts no client authority fields."]}
                )
        return cast(dict[str, object], super().to_internal_value(data))


class AccountActorAuthorityRawSourcePublishView(APIView):
    """Publish one authenticated session's raw authority facts."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    http_method_names = ["post", "options"]

    def post(self, request: Request) -> Response:
        """Validate an empty body, then publish server-derived facts atomically."""

        serializer = AccountActorAuthorityRawSourcePublishRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            publisher = build_account_actor_authority_raw_source_publisher(
                authenticated_user=request.user,
                session=request._request.session,
            )
            receipt = publisher.execute(PublishAccountActorAuthorityRawSourceV3Command())
        except AccountActorAuthorityRawSourceV3Corruption:
            return _error(
                code="account_authority_integrity_failure",
                detail="The Account authority source failed integrity checks.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (
            AccountActorAuthorityRawSourceV3Conflict,
            AccountActorAuthorityRawSourceV3Unavailable,
            TypeError,
            ValueError,
        ):
            return _error(
                code="account_authority_publication_conflict",
                detail="The authenticated Account authority cannot be published.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return Response({"data": receipt.to_payload()}, status=status.HTTP_201_CREATED)


def _error(*, code: str, detail: str, http_status: int) -> Response:
    """Return a stable error shape without serializing internal exception details."""

    return Response({"code": code, "detail": detail}, status=http_status)


__all__ = [
    "AccountActorAuthorityRawSourcePublishRequestSerializer",
    "AccountActorAuthorityRawSourcePublishView",
]
