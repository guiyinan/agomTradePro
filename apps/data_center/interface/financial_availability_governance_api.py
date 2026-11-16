"""Session-authenticated JSON endpoints for C2 Owner apply and revoke events."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, TypeAlias, TypeVar, cast

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityOwnerEventIdentity,
)
from apps.data_center.financial_availability_owner_api_composition import (
    apply_financial_availability_owner_request,
    revoke_financial_availability_owner_request,
)

_ViewMethod = TypeVar("_ViewMethod", bound=Callable[..., object])
_typed_extend_schema = cast(
    Callable[..., Callable[[_ViewMethod], _ViewMethod]],
    extend_schema,
)

SerializerField: TypeAlias = serializers.Field[Any, Any, Any, Any]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


class _StrictJsonSerializer(serializers.Serializer[dict[str, object]]):
    """Require an exact JSON object and reject unknown fields before coercion."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Reject non-object or extra request keys without silently dropping them."""

        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Expected a JSON object.")
        raw_keys = tuple(data.keys())
        if any(type(key) is not str for key in raw_keys):
            raise serializers.ValidationError("Object keys must be strings.")
        unknown = sorted(set(cast(tuple[str, ...], raw_keys)) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {"non_field_errors": [f"Unknown fields: {', '.join(unknown)}"]}
            )
        return cast(dict[str, object], super().to_internal_value(data))


class _ExactTextField(serializers.CharField):
    """Accept a real trimmed JSON string without coercion or silent cleanup."""

    def to_internal_value(self, data: object) -> str:
        """Reject coercible numbers and retain the string the Owner reviewed."""

        if type(data) is not str or data.strip() != data:
            self.fail("invalid")
        return super().to_internal_value(data)


class _DigestField(_ExactTextField):
    """Validate one canonical lower-case SHA-256 identity."""

    default_error_messages = {"invalid": "Expected a lower-case SHA-256 digest."}

    def __init__(self) -> None:
        """Set the fixed digest width without accepting coercion or trimming."""

        super().__init__(min_length=64, max_length=64, trim_whitespace=False)

    def run_validation(self, data: object = serializers.empty) -> str:
        """Require exactly 64 lower-case hexadecimal characters."""

        result = super().run_validation(data)
        if not isinstance(result, str):
            self.fail("invalid")
        if _SHA256_RE.fullmatch(result) is None:
            self.fail("invalid")
        return result


class _UuidField(_ExactTextField):
    """Validate one lower-case hyphenated UUID selector."""

    default_error_messages = {"invalid": "Expected a canonical lower-case UUID."}

    def __init__(self) -> None:
        """Set the canonical UUID width and preserve exact text."""

        super().__init__(min_length=36, max_length=36, trim_whitespace=False)

    def run_validation(self, data: object = serializers.empty) -> str:
        """Reject UUID aliases and uppercase forms before composition."""

        result = super().run_validation(data)
        if not isinstance(result, str):
            self.fail("invalid")
        if _UUID_RE.fullmatch(result) is None:
            self.fail("invalid")
        return result


class _OwnerRecordSerializer(_StrictJsonSerializer):
    """Validate the exact stored-record envelope before Core codec decoding."""

    schema = _ExactTextField(max_length=80, trim_whitespace=False)
    record_id = _ExactTextField(max_length=200, trim_whitespace=False)
    record_version = _ExactTextField(max_length=64, trim_whitespace=False)
    exchange = _ExactTextField(max_length=32, trim_whitespace=False)
    kind = serializers.ChoiceField(choices=("opening_rule", "disclosure_policy"))
    recorded_at = _ExactTextField(max_length=40, trim_whitespace=False)
    content = serializers.JSONField()
    content_sha256 = _DigestField()

    def get_fields(self) -> dict[str, SerializerField]:
        """Register the public source field without overriding DRF serializer state."""

        fields = super().get_fields()
        fields["source"] = serializers.JSONField(allow_null=True)
        return fields

    def validate_schema(self, value: str) -> str:
        """Accept only the persisted C2 record schema version."""

        if value != "data_center.financial-availability-record.v1":
            raise serializers.ValidationError("Unknown C2 governance record schema.")
        return value

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require typed JSON objects for both content and optional source binding."""

        if type(attrs["content"]) is not dict:
            raise serializers.ValidationError({"content": "Expected a JSON object."})
        source = attrs["source"]
        if source is not None and type(source) is not dict:
            raise serializers.ValidationError({"source": "Expected a JSON object or null."})
        return attrs


class _RevokeTargetSerializer(_StrictJsonSerializer):
    """Validate only exact immutable identities used to locate the real apply."""

    record_id = _ExactTextField(max_length=200, trim_whitespace=False)
    record_version = _ExactTextField(max_length=64, trim_whitespace=False)
    record_content_sha256 = _DigestField()
    apply_event_id = _UuidField()
    apply_event_sha256 = _DigestField()


class ApplyFinancialAvailabilityOwnerRequestSerializer(_StrictJsonSerializer):
    """Validate one serialized record and reason; no request principal fields."""

    record = _OwnerRecordSerializer()
    reason = _ExactTextField(max_length=1000, trim_whitespace=False)


class RevokeFinancialAvailabilityOwnerRequestSerializer(_StrictJsonSerializer):
    """Validate the persisted record/apply identity and explicit reason only."""

    target = _RevokeTargetSerializer()
    reason = _ExactTextField(max_length=1000, trim_whitespace=False)


class _RecordResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Document the exact persisted row returned after server-side restamping."""

    schema = serializers.CharField()
    record_id = serializers.CharField()
    record_version = serializers.CharField()
    exchange = serializers.CharField()
    kind = serializers.CharField()
    recorded_at = serializers.DateTimeField()
    content = serializers.JSONField()
    content_sha256 = serializers.CharField()

    def get_fields(self) -> dict[str, SerializerField]:
        """Register the public source field without overriding DRF serializer state."""

        fields = super().get_fields()
        fields["source"] = serializers.JSONField(allow_null=True)
        return fields


class _OwnerEventResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Document the local apply/revoke event returned by the configuration write."""

    action = serializers.CharField()
    event_id = serializers.UUIDField()
    event_sha256 = serializers.CharField()
    record_id = serializers.CharField()
    record_version = serializers.CharField()
    record_content_sha256 = serializers.CharField()
    resulting_content_sha256 = serializers.CharField()
    actor_user_id = serializers.IntegerField()
    permission_id = serializers.IntegerField()
    permission_app_label = serializers.CharField()
    permission_codename = serializers.CharField()
    permission_verified_at = serializers.DateTimeField()
    occurred_at = serializers.DateTimeField()
    recorded_at = serializers.DateTimeField()
    reason = serializers.CharField()
    predecessor_apply_event_id = serializers.UUIDField(allow_null=True)
    predecessor_apply_event_sha256 = serializers.CharField(allow_null=True)


class _ApplySuccessSerializer(serializers.Serializer[dict[str, object]]):
    """Document the immutable configuration row and its local Owner event."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    record = _RecordResponseSerializer()
    owner_event = _OwnerEventResponseSerializer()


class _RevokeSuccessSerializer(serializers.Serializer[dict[str, object]]):
    """Document one appended local revoke event."""

    outcome = serializers.ChoiceField(choices=("success",))
    success = serializers.BooleanField()
    owner_event = _OwnerEventResponseSerializer()


class _ErrorResponseSerializer(serializers.Serializer[dict[str, object]]):
    """Document the shared JSON error shape."""

    error = serializers.CharField()
    code = serializers.CharField()
    details = serializers.JSONField(required=False)


def _event_payload(event: FinancialAvailabilityOwnerEventIdentity) -> dict[str, object]:
    """Present server-created event facts without treating them as SystemAudit."""

    event.__post_init__()
    return {
        "action": event.action.value,
        "event_id": str(event.event_id),
        "event_sha256": event.event_sha256,
        "record_id": event.record_id,
        "record_version": event.record_version,
        "record_content_sha256": event.record_content_sha256,
        "resulting_content_sha256": event.resulting_content_sha256,
        "actor_user_id": event.actor_user_id,
        "permission_id": event.permission_id,
        "permission_app_label": event.permission_app_label,
        "permission_codename": event.permission_codename,
        "permission_verified_at": event.permission_verified_at.isoformat(),
        "occurred_at": event.occurred_at.isoformat(),
        "recorded_at": event.recorded_at.isoformat(),
        "reason": event.reason,
        "predecessor_apply_event_id": (
            str(event.predecessor_apply_event_id)
            if event.predecessor_apply_event_id is not None
            else None
        ),
        "predecessor_apply_event_sha256": event.predecessor_apply_event_sha256,
    }


class _FinancialAvailabilityOwnerJsonAPIView(APIView):
    """Require real Django session authentication and JSON for Owner operations."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)


class ApplyFinancialAvailabilityOwnerView(_FinancialAvailabilityOwnerJsonAPIView):
    """Append one versioned C2 configuration and its authenticated apply event."""

    @_typed_extend_schema(
        request=ApplyFinancialAvailabilityOwnerRequestSerializer,
        responses={
            status.HTTP_201_CREATED: _ApplySuccessSerializer,
            status.HTTP_400_BAD_REQUEST: _ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: _ErrorResponseSerializer,
            status.HTTP_405_METHOD_NOT_ALLOWED: _ErrorResponseSerializer,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: _ErrorResponseSerializer,
            status.HTTP_422_UNPROCESSABLE_ENTITY: _ErrorResponseSerializer,
        },
        operation_id="applyFinancialAvailabilityGovernance",
        tags=("Data Center Financial Availability",),
    )
    def post(self, request: Request) -> Response:
        """Validate an exact record and delegate principal proof to trusted composition."""

        serializer = ApplyFinancialAvailabilityOwnerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_payload = cast(dict[str, object], serializer.validated_data["record"])
        reason = cast(str, serializer.validated_data["reason"])
        persisted, event = apply_financial_availability_owner_request(
            request._request,
            record_payload=record_payload,
            reason=reason,
        )
        persisted.__post_init__()
        return Response(
            {
                "outcome": "success",
                "success": True,
                "record": {**persisted.to_payload(), "content_sha256": persisted.content_sha256},
                "owner_event": _event_payload(event),
            },
            status=status.HTTP_201_CREATED,
        )


class RevokeFinancialAvailabilityOwnerView(_FinancialAvailabilityOwnerJsonAPIView):
    """Append a revoke only for an exact persisted record and apply-event identity."""

    @_typed_extend_schema(
        request=RevokeFinancialAvailabilityOwnerRequestSerializer,
        responses={
            status.HTTP_201_CREATED: _RevokeSuccessSerializer,
            status.HTTP_400_BAD_REQUEST: _ErrorResponseSerializer,
            status.HTTP_403_FORBIDDEN: _ErrorResponseSerializer,
            status.HTTP_405_METHOD_NOT_ALLOWED: _ErrorResponseSerializer,
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: _ErrorResponseSerializer,
            status.HTTP_422_UNPROCESSABLE_ENTITY: _ErrorResponseSerializer,
        },
        operation_id="revokeFinancialAvailabilityGovernance",
        tags=("Data Center Financial Availability",),
    )
    def post(self, request: Request) -> Response:
        """Resolve target identities from the database and append a server-clocked revoke."""

        serializer = RevokeFinancialAvailabilityOwnerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = cast(dict[str, str], serializer.validated_data["target"])
        reason = cast(str, serializer.validated_data["reason"])
        event = revoke_financial_availability_owner_request(
            request._request,
            target=target,
            reason=reason,
        )
        return Response(
            {
                "outcome": "success",
                "success": True,
                "owner_event": _event_payload(event),
            },
            status=status.HTTP_201_CREATED,
        )


__all__ = [
    "ApplyFinancialAvailabilityOwnerRequestSerializer",
    "ApplyFinancialAvailabilityOwnerView",
    "RevokeFinancialAvailabilityOwnerRequestSerializer",
    "RevokeFinancialAvailabilityOwnerView",
]
