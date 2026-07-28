"""Flat TUI adapters for staff semantic-key governance."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response

from apps.ai_capability.domain.semantic_governance import (
    SemanticCorrection,
    SemanticCorrectionBatch,
    SemanticIdempotencyConflict,
)
from apps.ai_capability.interface.semantic_governance_serializers import (
    StrictFieldsSerializer,
    serialize_batch_result,
)
from apps.ai_capability.interface.semantic_governance_views import (
    StaffSemanticGovernanceAPIView,
)


class SemanticSingleCorrectionSerializer(StrictFieldsSerializer):
    """Validate one flat correction and build the owner Domain batch."""

    idempotency_key = serializers.CharField(max_length=255, trim_whitespace=True)
    reason = serializers.CharField(max_length=2000, trim_whitespace=True)
    capability_key = serializers.CharField(max_length=255, trim_whitespace=True)
    action = serializers.ChoiceField(choices=("set", "remove"))
    semantic_key = serializers.CharField(
        max_length=255,
        required=False,
        allow_null=True,
        allow_blank=False,
        trim_whitespace=True,
    )

    def to_domain(self) -> SemanticCorrectionBatch:
        """Convert validated flat fields into a one-correction batch."""

        if not hasattr(self, "validated_data"):
            raise RuntimeError("serializer must be validated before conversion")
        data: dict[str, Any] = self.validated_data
        return SemanticCorrectionBatch(
            idempotency_key=str(data["idempotency_key"]),
            reason=str(data["reason"]),
            corrections=(
                SemanticCorrection(
                    capability_key=str(data["capability_key"]),
                    action=data["action"],
                    semantic_key=data.get("semantic_key"),
                ),
            ),
        )


class SemanticSinglePreviewView(StaffSemanticGovernanceAPIView):
    """Preview one semantic correction from flat TUI fields."""

    def post(self, request: Request) -> Response:
        """Validate and preview without writes."""

        serializer = SemanticSingleCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = self.build_service().preview(serializer.to_domain())
        except ValueError as exc:
            return Response(
                {"error": str(exc), "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_batch_result(result))


class SemanticSingleApplyView(StaffSemanticGovernanceAPIView):
    """Apply one semantic correction from flat TUI fields."""

    def post(self, request: Request) -> Response:
        """Validate, revalidate and persist one correction."""

        serializer = SemanticSingleCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        operator_id = request.user.pk
        if operator_id is None:
            return Response(
                {"error": "Persisted operator identity required", "code": "PERMISSION_DENIED"},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            result = self.build_service().apply(
                serializer.to_domain(),
                operator_id=operator_id,
            )
        except SemanticIdempotencyConflict as exc:
            return Response(
                {"error": str(exc), "code": "IDEMPOTENCY_CONFLICT"},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as exc:
            return Response(
                {"error": str(exc), "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_batch_result(result))
