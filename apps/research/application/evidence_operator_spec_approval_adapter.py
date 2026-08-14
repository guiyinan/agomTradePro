"""Pure projection of an external approval into Research activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecOwnerApproval,
)


@dataclass(frozen=True, slots=True)
class ExternalOperatorSpecApprovalProjection:
    """Data-only boundary projection supplied by a composition root."""

    owner: str
    capability: str
    approval_id: str
    approval_version: str
    owner_record_hash: str
    operator_id: str
    operator_version: str
    definition_hash: str
    supersedes_activation_hash: str | None
    approved_by: str
    issued_at: datetime
    valid_until: datetime


def project_operator_spec_owner_approval(
    projection: ExternalOperatorSpecApprovalProjection,
    *,
    approval_id: str,
    approval_version: str,
    operator_id: str,
    operator_version: str,
    definition_hash: str,
    supersedes_activation_hash: str | None,
) -> EvidenceOperatorSpecOwnerApproval:
    """Revalidate authority and exact selectors before creating a receipt input."""

    if (
        projection.owner != "risk_center"
        or projection.capability != "evidence_operator_spec_activation"
        or projection.approval_id != approval_id
        or projection.approval_version != approval_version
        or projection.operator_id != operator_id
        or projection.operator_version != operator_version
        or projection.definition_hash != definition_hash
        or projection.supersedes_activation_hash != supersedes_activation_hash
    ):
        raise EvidenceOperatorSpecCorruption(
            "Risk Center operator specification approval selector mismatch"
        )
    return EvidenceOperatorSpecOwnerApproval(
        approval_id=projection.approval_id,
        approval_version=projection.approval_version,
        owner_record_id=projection.approval_id,
        owner_record_version=projection.approval_version,
        owner_record_hash=projection.owner_record_hash,
        operator_id=projection.operator_id,
        operator_version=projection.operator_version,
        definition_hash=projection.definition_hash,
        supersedes_activation_hash=projection.supersedes_activation_hash,
        approved_by=projection.approved_by,
        issued_at=projection.issued_at,
        valid_until=projection.valid_until,
    )


__all__ = [
    "ExternalOperatorSpecApprovalProjection",
    "project_operator_spec_owner_approval",
]
