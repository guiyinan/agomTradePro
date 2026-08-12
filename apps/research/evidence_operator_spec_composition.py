"""Django composition for approved Evidence operator specification lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from apps.research.application.evidence_operator_spec_approval_adapter import (
    RiskCenterOperatorSpecApprovalAdapter,
)
from apps.research.application.evidence_operator_spec_lifecycle import (
    ActivateEvidenceOperatorSpec,
    ExactEvidenceOperatorSpecDefinitionProvider,
    GetActiveOperatorSpec,
    GetExactActivatedOperatorSpec,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
)
from apps.risk_center.application.evidence_operator_spec_approval import (
    GetEvidenceOperatorSpecApprovalForDefinition,
)
from apps.risk_center.infrastructure.evidence_operator_spec_approval_repository import (
    DjangoEvidenceOperatorSpecApprovalRepository,
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
    approval_query = RiskCenterOperatorSpecApprovalAdapter(
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
