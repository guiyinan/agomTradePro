"""Application adapter from Risk Center approvals to Research activation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecOwnerApproval,
)
from apps.risk_center.application.evidence_operator_spec_approval import (
    GetEvidenceOperatorSpecApprovalForDefinition,
    GetEvidenceOperatorSpecApprovalForDefinitionCommand,
)
from apps.risk_center.domain.evidence_operator_spec_approval import (
    EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY,
    EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER,
    EvidenceOperatorSpecApprovalRecord,
)


class RiskCenterOperatorSpecApprovalDefinitionQuery(Protocol):
    """Narrow Risk Center Application facade consumed by this adapter."""

    def execute(
        self,
        command: GetEvidenceOperatorSpecApprovalForDefinitionCommand,
    ) -> EvidenceOperatorSpecApprovalRecord | None:
        """Return one exact validated owner approval or no projection."""


class RiskCenterOperatorSpecApprovalAdapter:
    """Project one exact Risk Center approval without exposing its repository."""

    __slots__ = ("_query",)

    def __init__(self, query: RiskCenterOperatorSpecApprovalDefinitionQuery) -> None:
        self._query = query

    def get_exact(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecOwnerApproval | None:
        """Return a revalidated Research projection for one exact selector."""

        record = self._query.execute(
            GetEvidenceOperatorSpecApprovalForDefinitionCommand(
                approval_id=approval_id,
                approval_version=approval_version,
                operator_id=operator_id,
                operator_version=operator_version,
                definition_hash=definition_hash,
                supersedes_activation_hash=supersedes_activation_hash,
                as_of=as_of,
            )
        )
        if record is None:
            return None
        self._require_selector(
            record,
            approval_id=approval_id,
            approval_version=approval_version,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
        )
        subject = record.subject
        return EvidenceOperatorSpecOwnerApproval(
            approval_id=record.approval_id,
            approval_version=record.approval_version,
            owner_record_id=record.approval_id,
            owner_record_version=record.approval_version,
            owner_record_hash=record.content_hash,
            operator_id=subject.operator_id,
            operator_version=subject.operator_version,
            definition_hash=subject.definition_hash,
            supersedes_activation_hash=subject.supersedes_activation_hash,
            approved_by=record.approved_by.actor_id,
            issued_at=record.issued_at,
            valid_until=record.valid_until,
        )

    @staticmethod
    def _require_selector(
        record: EvidenceOperatorSpecApprovalRecord,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
    ) -> None:
        subject = record.subject
        if (
            record.owner != EVIDENCE_OPERATOR_SPEC_APPROVAL_OWNER
            or record.capability != EVIDENCE_OPERATOR_SPEC_APPROVAL_CAPABILITY
            or record.approval_id != approval_id
            or record.approval_version != approval_version
            or subject.operator_id != operator_id
            or subject.operator_version != operator_version
            or subject.definition_hash != definition_hash
            or subject.supersedes_activation_hash != supersedes_activation_hash
        ):
            raise EvidenceOperatorSpecCorruption(
                "Risk Center operator specification approval selector mismatch"
            )


__all__ = [
    "RiskCenterOperatorSpecApprovalAdapter",
    "RiskCenterOperatorSpecApprovalDefinitionQuery",
]
