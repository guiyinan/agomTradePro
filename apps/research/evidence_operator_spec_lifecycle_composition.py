"""Research-owned composition for approved Evidence operator specifications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.research.application.evidence_operator_spec_lifecycle import (
    ActivateEvidenceOperatorSpec,
    ExactEvidenceOperatorSpecDefinitionProvider,
    GetActiveOperatorSpec,
    GetExactActivatedOperatorSpec,
    RiskCenterEvidenceOperatorSpecApprovalQuery,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
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
    approval_query: RiskCenterEvidenceOperatorSpecApprovalQuery,
    using: str = "default",
) -> DjangoEvidenceOperatorSpecRuntime:
    """Wire Research activation to an injected approval facade.

    The approval owner is deliberately injected at the composition boundary so
    Research does not statically depend on Risk Center.  A higher-level
    composition root must provide the same-alias, exact-read adapter.
    """

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
