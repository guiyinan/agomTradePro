"""Authenticated owner endpoint for explicitly publishing an M1 policy revision."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.m1_rebalance_risk_policy import (
    M1RiskPolicyAlreadyRevokedError,
    M1RiskPolicyIdempotencyConflictError,
    M1RiskPolicyNotFoundError,
    M1RiskPolicySourceCorruptError,
    M1RiskPolicyValidationError,
)
from apps.simulated_trading import m1_risk_policy_composition
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    M1RiskPolicyOwnerDenied,
    OwnerM1RiskPolicyRevokeRequest,
    build_m1_risk_policy_idempotency_context,
)
from apps.simulated_trading.interface.m1_risk_policy_serializers import (
    M1RiskPolicyErrorResponseSerializer,
    M1RiskPolicyRevisionResponseSerializer,
    M1RiskPolicyRevocationResponseSerializer,
    OwnerM1RiskPolicyRevokeSerializer,
    revision_response,
    revocation_response,
)
from apps.simulated_trading.interface.m1_risk_policy_tui_serializers import (
    OwnerM1RiskPolicyFlatPublishSerializer,
)

ViewMethodT = TypeVar("ViewMethodT", bound=Callable[..., Any])


class ExtendSchemaProtocol(Protocol):
    """Typed façade for the existing drf-spectacular decorator boundary."""

    def __call__(self, *args: Any, **kwargs: Any) -> Callable[[ViewMethodT], ViewMethodT]:
        """Preserve the signature of the view method being decorated."""
        ...


typed_extend_schema = cast(ExtendSchemaProtocol, extend_schema)


class OwnerM1RiskPolicyRevisionAPIView(APIView):
    """Publish one new M1 preview policy for the authenticated account owner."""

    permission_classes = (IsAuthenticated,)

    @typed_extend_schema(
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Stable identity for this owner submission and its explicit retries.",
            )
        ],
        request=OwnerM1RiskPolicyFlatPublishSerializer,
        responses={
            201: M1RiskPolicyRevisionResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: M1RiskPolicyErrorResponseSerializer,
            409: M1RiskPolicyErrorResponseSerializer,
        },
    )
    def post(self, request: Request, account_id: int) -> Response:
        """Validate an explicit risk decision and bind it to current source facts."""

        serializer = OwnerM1RiskPolicyFlatPublishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_payload = request.data
        if not isinstance(request_payload, Mapping):
            return Response(
                {"code": "M1_RISK_POLICY_REQUEST_BODY_NOT_OBJECT"},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        raw_actor_id = getattr(request.user, "pk", None)
        if type(raw_actor_id) is not int or raw_actor_id <= 0:
            return Response(
                {"code": "M1_RISK_POLICY_OWNER_REQUIRED"},
                status=status.HTTP_403_FORBIDDEN,
                content_type="application/json",
            )
        try:
            idempotency = build_m1_risk_policy_idempotency_context(
                account_id=account_id,
                actor_user_id=raw_actor_id,
                operation="publish",
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_payload=request_payload,
            )
        except (TypeError, ValueError):
            return Response(
                {"code": "M1_RISK_POLICY_IDEMPOTENCY_KEY_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        try:
            revision = m1_risk_policy_composition.build_owner_m1_risk_policy_publisher().execute(
                account_id=account_id,
                authenticated_actor_id=raw_actor_id,
                request=serializer.to_application_request(),
                idempotency=idempotency,
            )
        except M1RiskPolicyOwnerDenied:
            return Response(
                {"code": "M1_RISK_POLICY_OWNER_REQUIRED"},
                status=status.HTTP_403_FORBIDDEN,
                content_type="application/json",
            )
        except M1RiskPolicyIdempotencyConflictError:
            return Response(
                {"code": "M1_RISK_POLICY_IDEMPOTENCY_CONFLICT"},
                status=status.HTTP_409_CONFLICT,
                content_type="application/json",
            )
        except M1RiskPolicySourceCorruptError:
            return Response(
                {"code": "M1_RISK_POLICY_SOURCE_CORRUPT"},
                status=status.HTTP_409_CONFLICT,
                content_type="application/json",
            )
        except M1RiskPolicyValidationError as exc:
            return Response(
                {"code": "M1_RISK_POLICY_INVALID", "reason_codes": list(exc.reason_codes)},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        response_serializer = M1RiskPolicyRevisionResponseSerializer(
            data=revision_response(revision)
        )
        response_serializer.is_valid(raise_exception=True)
        return Response(
            cast(dict[str, object], response_serializer.validated_data),
            status=status.HTTP_201_CREATED,
            content_type="application/json",
        )


class OwnerM1RiskPolicyRevocationAPIView(APIView):
    """Append a reasoned owner revocation without editing the source revision."""

    permission_classes = (IsAuthenticated,)

    @typed_extend_schema(
        parameters=[
            OpenApiParameter(
                name="Idempotency-Key",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description="Stable identity for this owner submission and its explicit retries.",
            )
        ],
        request=OwnerM1RiskPolicyRevokeSerializer,
        responses={
            200: M1RiskPolicyRevocationResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: M1RiskPolicyErrorResponseSerializer,
            404: M1RiskPolicyErrorResponseSerializer,
            409: M1RiskPolicyErrorResponseSerializer,
        },
    )
    def post(
        self,
        request: Request,
        account_id: int,
        risk_policy_version: UUID,
    ) -> Response:
        """Revoke one exact policy version and report its actual audit timestamp."""

        serializer = OwnerM1RiskPolicyRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_payload = request.data
        if not isinstance(request_payload, Mapping):
            return Response(
                {"code": "M1_RISK_POLICY_REQUEST_BODY_NOT_OBJECT"},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        raw_actor_id = getattr(request.user, "pk", None)
        if type(raw_actor_id) is not int or raw_actor_id <= 0:
            return Response(
                {"code": "M1_RISK_POLICY_OWNER_REQUIRED"},
                status=status.HTTP_403_FORBIDDEN,
                content_type="application/json",
            )
        try:
            idempotency = build_m1_risk_policy_idempotency_context(
                account_id=account_id,
                actor_user_id=raw_actor_id,
                operation="revoke",
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                request_payload=request_payload,
                resource_id=str(risk_policy_version),
            )
        except (TypeError, ValueError):
            return Response(
                {"code": "M1_RISK_POLICY_IDEMPOTENCY_KEY_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        reason = serializer.validated_data.get("reason")
        if type(reason) is not str:
            return Response(
                {"code": "M1_RISK_POLICY_REVOCATION_REASON_REQUIRED"},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        try:
            revision = m1_risk_policy_composition.build_owner_m1_risk_policy_revoker().execute(
                account_id=account_id,
                risk_policy_version=str(risk_policy_version),
                authenticated_actor_id=raw_actor_id,
                request=OwnerM1RiskPolicyRevokeRequest(reason=reason),
                idempotency=idempotency,
            )
        except M1RiskPolicyOwnerDenied:
            return Response(
                {"code": "M1_RISK_POLICY_OWNER_REQUIRED"},
                status=status.HTTP_403_FORBIDDEN,
                content_type="application/json",
            )
        except M1RiskPolicyIdempotencyConflictError:
            return Response(
                {"code": "M1_RISK_POLICY_IDEMPOTENCY_CONFLICT"},
                status=status.HTTP_409_CONFLICT,
                content_type="application/json",
            )
        except M1RiskPolicySourceCorruptError:
            return Response(
                {"code": "M1_RISK_POLICY_SOURCE_CORRUPT"},
                status=status.HTTP_409_CONFLICT,
                content_type="application/json",
            )
        except M1RiskPolicyNotFoundError:
            return Response(
                {"code": "M1_RISK_POLICY_VERSION_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
                content_type="application/json",
            )
        except M1RiskPolicyAlreadyRevokedError:
            return Response(
                {"code": "M1_RISK_POLICY_ALREADY_REVOKED"},
                status=status.HTTP_409_CONFLICT,
                content_type="application/json",
            )
        except M1RiskPolicyValidationError as exc:
            return Response(
                {"code": "M1_RISK_POLICY_INVALID", "reason_codes": list(exc.reason_codes)},
                status=status.HTTP_400_BAD_REQUEST,
                content_type="application/json",
            )
        response_serializer = M1RiskPolicyRevocationResponseSerializer(
            data=revocation_response(revision)
        )
        response_serializer.is_valid(raise_exception=True)
        return Response(
            cast(dict[str, object], response_serializer.validated_data),
            status=status.HTTP_200_OK,
            content_type="application/json",
        )


__all__: tuple[str, ...] = (
    "OwnerM1RiskPolicyRevisionAPIView",
    "OwnerM1RiskPolicyRevocationAPIView",
)
