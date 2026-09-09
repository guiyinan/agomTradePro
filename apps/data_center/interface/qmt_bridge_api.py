"""Owner pairing and signed machine contracts for the integrated QMT bridge."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.data_center.domain.qmt_bridge import BridgeBatch, BridgeSample
from apps.data_center.qmt_bridge_composition import build_qmt_bridge_service
from core.exceptions import AuthorizationError, DuplicateResourceError, ResourceNotFoundError


class AssetSelectionField(serializers.ListField):
    """Accept a TUI comma-separated selection or a canonical JSON list."""

    def to_internal_value(self, data: Any) -> list[str]:
        """Normalize user entry before list validation."""
        if isinstance(data, str):
            data = data.replace("，", ",").replace("\n", ",").split(",")
            data = [item.strip() for item in data if item.strip()]
        return super().to_internal_value(data)


class SourceTimeField(serializers.DateTimeField):
    """Do not assign the server timezone to missing source timezone information."""

    def to_internal_value(self, value: Any) -> datetime:
        """Require an explicit timezone before DRF conversion."""
        try:
            parsed = (
                value
                if isinstance(value, datetime)
                else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            )
        except ValueError as exc:
            raise serializers.ValidationError("Invalid source timestamp") from exc
        if parsed.utcoffset() is None:
            raise serializers.ValidationError("Source timestamp must include a timezone")
        return super().to_internal_value(value)


class BindingSerializer(serializers.Serializer[dict[str, Any]]):
    """A user binds a local Agent and bounded catalog selection, never an owner ID."""

    agent_id = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,100}$")
    assets = AssetSelectionField(
        child=serializers.CharField(max_length=20), min_length=1, max_length=200
    )


class PairSerializer(serializers.Serializer[dict[str, Any]]):
    """Single-use pairing claim with an exact local Agent identity."""

    agent_id = serializers.RegexField(r"^[a-zA-Z0-9_-]{1,100}$")
    pairing_code = serializers.CharField(min_length=32, max_length=128, trim_whitespace=False)


class ControlSerializer(serializers.Serializer[dict[str, Any]]):
    """Independent collection controls; no trading fields are accepted."""

    action = serializers.ChoiceField(choices=["approve", "pause", "resume", "revoke", "repair"])
    provider_id = serializers.IntegerField(min_value=1, required=False)
    quote_multiplier = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0.0001"), required=False
    )
    bar_multiplier = serializers.DecimalField(
        max_digits=12, decimal_places=4, min_value=Decimal("0.0001"), required=False
    )
    poll_seconds = serializers.IntegerField(min_value=1, max_value=60, default=10)
    freshness_seconds = serializers.IntegerField(min_value=1, max_value=3600, default=60)


class SampleSerializer(serializers.Serializer[dict[str, Any]]):
    """Convert transport numbers to precise, bounded domain values."""

    asset_code = serializers.CharField(max_length=20)
    observed_at = SourceTimeField()
    price = serializers.DecimalField(max_digits=18, decimal_places=4)
    open = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False
    )
    high = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False
    )
    low = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True, required=False)
    prev_close = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False
    )
    volume = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True, required=False
    )
    amount = serializers.DecimalField(
        max_digits=24, decimal_places=2, allow_null=True, required=False
    )
    bar_date = serializers.DateField(allow_null=True, required=False)


class BatchSerializer(serializers.Serializer[dict[str, Any]]):
    """Bounded immutable batch envelope."""

    batch_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["quote", "bar"])
    collected_at = SourceTimeField()
    samples: serializers.ListSerializer[dict[str, Any]] = serializers.ListSerializer(
        child=SampleSerializer(), min_length=1, max_length=500
    )


def _owner_id(request: Request) -> int:
    """Require a persistent authenticated owner before any binding operation."""
    if not request.user.is_authenticated or request.user.pk is None:
        raise AuthorizationError("A signed-in user is required")
    return request.user.pk


def _response(call: Callable[[], object]) -> Response:
    try:
        response = Response({"success": True, "data": call()})
    except AuthorizationError as exc:
        response = Response({"success": False, "error": str(exc)}, status=403)
    except ResourceNotFoundError as exc:
        response = Response({"success": False, "error": str(exc)}, status=404)
    except DuplicateResourceError as exc:
        response = Response({"success": False, "error": str(exc)}, status=409)
    except ValueError as exc:
        response = Response({"success": False, "error": str(exc)}, status=400)
    response["Cache-Control"] = "no-store"
    return response


class QmtBindingsView(APIView):
    """Create/list bindings for the authenticated owner."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        """Return this user's collection state."""
        return _response(lambda: build_qmt_bridge_service().list_bindings(_owner_id(request)))

    def post(self, request: Request) -> Response:
        """Issue a one-time pairing code for this server."""
        serializer = BindingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return _response(
            lambda: build_qmt_bridge_service().create(
                _owner_id(request),
                data["agent_id"],
                request.build_absolute_uri("/").rstrip("/"),
                tuple(data["assets"]),
            )
        )


class QmtBindingControlView(APIView):
    """Owner lifecycle actions and staff-only canonical provider approval."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, binding_id: UUID) -> Response:
        """Apply a scoped collection control and return its receipt."""
        serializer = ControlSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return _response(
            lambda: build_qmt_bridge_service().control(
                str(binding_id),
                _owner_id(request),
                bool(request.user.is_staff),
                **serializer.validated_data,
            )
        )


class QmtPairView(APIView):
    """Exchange a high-entropy one-time code; no session credentials are used."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        """Consume the code against this exact server origin."""
        serializer = PairSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return _response(
            lambda: build_qmt_bridge_service().pair(
                data["pairing_code"], data["agent_id"], request.build_absolute_uri("/").rstrip("/")
            )
        )


class QmtMachineView(APIView):
    """Signed machine requests, isolated from user-session and trading auth."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request: Request, operation: str) -> Response:
        """Fetch approved collection state or upload a validated fact batch."""
        return _response(lambda: self._execute(request, operation))

    @staticmethod
    def _execute(request: Request, operation: str) -> object:
        service = build_qmt_bridge_service()
        binding_id = request.headers.get("X-Bridge-Id", "")
        authorization = request.headers.get("Authorization", "")
        token = (
            authorization.removeprefix("QmtBridge ")
            if authorization.startswith("QmtBridge ")
            else ""
        )
        service.authenticate(
            binding_id,
            token,
            request.headers.get("X-Sent-At", ""),
            request.headers.get("X-Nonce", ""),
            request.headers.get("X-Signature", ""),
            request.path,
            request.body,
        )
        if operation == "plan":
            return service.plan(binding_id)
        serializer = BatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        batch = BridgeBatch(
            str(data["batch_id"]),
            data["kind"],
            data["collected_at"],
            tuple(BridgeSample(**sample) for sample in data["samples"]),
        )
        return service.execute(binding_id, batch)
