"""Staff-only HTTP interface for semantic-key governance."""

from __future__ import annotations

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.account.interface.authentication import (
    MultiTokenAuthentication,
    TerminalInternalAuthentication,
)
from apps.ai_capability.application.repository_provider import (
    get_capability_repository,
)
from apps.ai_capability.application.semantic_governance import (
    SemanticGovernanceService,
)
from apps.ai_capability.domain.semantic_governance import (
    SemanticIdempotencyConflict,
)

from .semantic_governance_serializers import (
    SemanticBatchRequestSerializer,
    serialize_audit_entries,
    serialize_batch_result,
    serialize_governance_snapshot,
)


class StaffSemanticGovernanceAPIView(APIView):
    """Common authentication and composition for governance endpoints."""

    authentication_classes = [
        MultiTokenAuthentication,
        SessionAuthentication,
        TerminalInternalAuthentication,
    ]
    permission_classes = [IsAdminUser]

    @staticmethod
    def build_service() -> SemanticGovernanceService:
        """Build the Application service at the Interface composition root."""

        return SemanticGovernanceService(get_capability_repository())


class SemanticGovernanceView(StaffSemanticGovernanceAPIView):
    """Inspect missing, conflicting, and orphaned semantic groups."""

    def get(self, request: Request) -> Response:
        """Return the current semantic governance inspection."""

        snapshot = self.build_service().inspect()
        return Response(serialize_governance_snapshot(snapshot))


class SemanticGovernancePreviewView(StaffSemanticGovernanceAPIView):
    """Preview a semantic correction batch without writes."""

    def post(self, request: Request) -> Response:
        """Validate and project one correction batch."""

        serializer = SemanticBatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = self.build_service().preview(serializer.to_domain())
        except ValueError as exc:
            return Response(
                {"error": str(exc), "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_batch_result(result))


class SemanticGovernanceApplyView(StaffSemanticGovernanceAPIView):
    """Apply a semantic correction batch transactionally."""

    def post(self, request: Request) -> Response:
        """Validate, revalidate, and persist one correction batch."""

        serializer = SemanticBatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = self.build_service().apply(
                serializer.to_domain(),
                operator_id=request.user.pk,
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


class SemanticGovernanceAuditView(StaffSemanticGovernanceAPIView):
    """List immutable semantic governance evidence."""

    def get(self, request: Request) -> Response:
        """Return a bounded, optionally capability-filtered audit list."""

        try:
            limit = int(request.query_params.get("limit", 100))
            entries = self.build_service().list_audit(
                limit=limit,
                capability_key=request.query_params.get("capability_key"),
            )
        except (TypeError, ValueError) as exc:
            return Response(
                {"error": str(exc), "code": "VALIDATION_ERROR"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(serialize_audit_entries(entries))
