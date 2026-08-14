"""Cross-app composition for approved Evidence operator specifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.evidence_operator_spec_approval_adapter import (
    ExternalOperatorSpecApprovalProjection,
    project_operator_spec_owner_approval,
)
from apps.research.application.evidence_operator_spec_lifecycle import (
    ActivateEvidenceOperatorSpec,
    EvidenceOperatorSpecOwnerApproval,
    ExactEvidenceOperatorSpecDefinitionProvider,
    GetActiveOperatorSpec,
    GetExactActivatedOperatorSpec,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
)
from apps.risk_center.application.evidence_operator_spec_approval import (
    GetEvidenceOperatorSpecApprovalForDefinition,
    GetEvidenceOperatorSpecApprovalForDefinitionCommand,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
    DjangoEvidenceOperatorSpecApprovalRepository,
)


class _RiskCenterOperatorSpecApprovalAdapter:
    """Project Risk Center records into the Research-owned approval port."""

    __slots__ = ("_query",)

    def __init__(self, query: GetEvidenceOperatorSpecApprovalForDefinition) -> None:
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
        subject = record.subject
        return project_operator_spec_owner_approval(
            ExternalOperatorSpecApprovalProjection(
                owner=record.owner,
                capability=record.capability,
                approval_id=record.approval_id,
                approval_version=record.approval_version,
                owner_record_hash=record.content_hash,
                operator_id=subject.operator_id,
                operator_version=subject.operator_version,
                definition_hash=subject.definition_hash,
                supersedes_activation_hash=subject.supersedes_activation_hash,
                approved_by=record.approved_by.actor_id,
                issued_at=record.issued_at,
                valid_until=record.valid_until,
            ),
            approval_id=approval_id,
            approval_version=approval_version,
            operator_id=operator_id,
            operator_version=operator_version,
            definition_hash=definition_hash,
            supersedes_activation_hash=supersedes_activation_hash,
        )


@dataclass(frozen=True, slots=True)
class DjangoEvidenceOperatorSpecRuntime:
    """ID-only activation plus exact/PIT reads for one database alias."""

    activate: ActivateEvidenceOperatorSpec
    get_exact: GetExactActivatedOperatorSpec
    get_active: GetActiveOperatorSpec


def build_django_evidence_operator_spec_runtime(
    *,
    definition_provider: ExactEvidenceOperatorSpecDefinitionProvider,
    using: str = "default",
) -> DjangoEvidenceOperatorSpecRuntime:
    """Wire Research activation to Risk Center's read-only approval facade."""

    risk_repository = DjangoEvidenceOperatorSpecApprovalRepository(using=using)
    approval_query = _RiskCenterOperatorSpecApprovalAdapter(
        GetEvidenceOperatorSpecApprovalForDefinition(risk_repository)
    )
    research_repository = DjangoEvidenceOperatorSpecLifecycleRepository(using=using)
    return DjangoEvidenceOperatorSpecRuntime(
        activate=ActivateEvidenceOperatorSpec(
            definition_provider=definition_provider,
            approval_query=approval_query,
            store=research_repository,
        ),
        get_exact=GetExactActivatedOperatorSpec(research_repository),
        get_active=GetActiveOperatorSpec(research_repository),
    )


__all__ = [
    "DjangoEvidenceOperatorSpecRuntime",
    "build_django_evidence_operator_spec_runtime",
]
