"""CSRF-protected human writes for operator-spec approval governance."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast

from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.risk_center.application.evidence_operator_spec_approval import (
    ApproveEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecApprovalConflict,
    EvidenceOperatorSpecApprovalCorruption,
    EvidenceOperatorSpecApprovalUnavailable,
    RegisterEvidenceOperatorSpecApprovalSubjectCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EvidenceOperatorSpecApprovalRecord,
    EvidenceOperatorSpecApprovalSubject,
)
from apps.risk_center.interface.evidence_operator_spec_approval_serializers import (
    ApproveOperatorSpecSerializer,
    RegisterOperatorSpecApprovalSubjectSerializer,
)
from core.integration.evidence_operator_spec_approval import (
    build_evidence_operator_spec_approval_write_runtime,
)

logger = logging.getLogger(__name__)


class _HumanStaffApprovalWriteView(APIView):
    """Deny non-session, non-staff, non-POST mutation attempts by default."""

    authentication_classes = [SessionAuthentication]
    permission_classes: list[type[BasePermission]] = [IsAuthenticated, IsAdminUser]
    http_method_names: list[str] = ["post", "options"]


class RegisterEvidenceOperatorSpecApprovalSubjectView(_HumanStaffApprovalWriteView):
    """Register one exact Research definition as a Risk Center subject."""

    def post(self, request: Request) -> Response:
        """Resolve the definition server-side and append its immutable subject."""

        serializer = RegisterOperatorSpecApprovalSubjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            runtime = build_evidence_operator_spec_approval_write_runtime(
                authenticated_user=request.user
            )
            subject = runtime.register_subject.execute(
                RegisterEvidenceOperatorSpecApprovalSubjectCommand(
                    subject_id=cast(str, values["subject_id"]),
                    subject_version=cast(str, values["subject_version"]),
                    operator_id=cast(str, values["operator_id"]),
                    operator_version=cast(str, values["operator_version"]),
                    as_of=timezone.now(),
                )
            )
        except EvidenceOperatorSpecApprovalCorruption:
            logger.exception("Operator-spec approval subject registration failed integrity checks")
            return _write_error(
                code="operator_spec_approval_integrity_failure",
                detail="The trusted approval graph failed integrity checks.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except EvidenceOperatorSpecApprovalUnavailable:
            return _write_error(
                code="operator_spec_approval_subject_unavailable",
                detail="The exact approval subject cannot be registered.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except (EvidenceOperatorSpecApprovalConflict, TypeError, ValueError):
            return _write_error(
                code="operator_spec_approval_subject_conflict",
                detail="The approval subject conflicts with immutable governance state.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"data": _subject_payload(subject)},
            status=status.HTTP_201_CREATED,
        )


class ApproveEvidenceOperatorSpecView(_HumanStaffApprovalWriteView):
    """Approve one already registered exact subject with another staff user."""

    def post(self, request: Request) -> Response:
        """Append approval with the server-authenticated actor and server clock."""

        serializer = ApproveOperatorSpecSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        try:
            runtime = build_evidence_operator_spec_approval_write_runtime(
                authenticated_user=request.user
            )
            approval = runtime.approve.execute(
                ApproveEvidenceOperatorSpecCommand(
                    subject_id=cast(str, values["subject_id"]),
                    subject_version=cast(str, values["subject_version"]),
                    approval_id=cast(str, values["approval_id"]),
                    approval_version=cast(str, values["approval_version"]),
                    as_of=timezone.now(),
                )
            )
        except EvidenceOperatorSpecApprovalCorruption:
            logger.exception("Operator-spec approval failed integrity checks")
            return _write_error(
                code="operator_spec_approval_integrity_failure",
                detail="The trusted approval graph failed integrity checks.",
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except EvidenceOperatorSpecApprovalUnavailable:
            return _write_error(
                code="operator_spec_approval_subject_unavailable",
                detail="The exact registered subject is unavailable for approval.",
                http_status=status.HTTP_409_CONFLICT,
            )
        except (EvidenceOperatorSpecApprovalConflict, TypeError, ValueError):
            return _write_error(
                code="operator_spec_approval_conflict",
                detail="The approval conflicts with immutable governance state.",
                http_status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"data": _approval_payload(approval)},
            status=status.HTTP_201_CREATED,
        )


def _write_error(*, code: str, detail: str, http_status: int) -> Response:
    return Response({"code": code, "detail": detail}, status=http_status)


def _subject_payload(subject: EvidenceOperatorSpecApprovalSubject) -> dict[str, object]:
    return {
        "subject_id": subject.subject_id,
        "subject_version": subject.subject_version,
        "operator_id": subject.operator_id,
        "operator_version": subject.operator_version,
        "definition_hash": subject.definition_hash,
        "supersedes_activation_hash": subject.supersedes_activation_hash,
        "requested_by": subject.requested_by.actor_id,
        "requested_at": _utc_text(subject.requested_at),
        "valid_until": _utc_text(subject.valid_until),
        "content_hash": subject.content_hash,
    }


def _approval_payload(approval: EvidenceOperatorSpecApprovalRecord) -> dict[str, object]:
    return {
        "owner": approval.owner,
        "capability": approval.capability,
        "approval_id": approval.approval_id,
        "approval_version": approval.approval_version,
        "subject_id": approval.subject.subject_id,
        "subject_version": approval.subject.subject_version,
        "subject_hash": approval.subject.content_hash,
        "approved_by": approval.approved_by.actor_id,
        "issued_at": _utc_text(approval.issued_at),
        "valid_until": _utc_text(approval.valid_until),
        "content_hash": approval.content_hash,
    }


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "ApproveEvidenceOperatorSpecView",
    "RegisterEvidenceOperatorSpecApprovalSubjectView",
]
