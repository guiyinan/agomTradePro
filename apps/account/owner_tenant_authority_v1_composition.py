"""Server-side composition for owner/tenant authority v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apps.account.account_owner_assignment_evidence_v3_composition import (
    build_current_account_owner_assignment_evidence_v3,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    ExactCurrentAccountActorAuthorityV3Reader,
)
from apps.account.application.owner_tenant_authority_v1 import (
    CurrentOwnerTenantAuthorityApproverProvider,
    GetCurrentOwnerTenantAuthorityV1,
    IssueOwnerTenantAuthorityV1,
    SupersedeOwnerTenantAuthorityV1,
)
from apps.account.infrastructure.owner_tenant_authority_v1_repository import (
    DjangoOwnerTenantAuthorityV1Repository,
)
from apps.research.application.evidence_reads import ScopedEvidenceReadFacade
from apps.research.evidence_composition import make_authorized_evidence_read_facade
from core.integration.owner_tenant_evidence_scope_v1 import (
    AuthenticatedOwnerTenantEvidenceScopeIssuerV1,
    AuthenticatedOwnerTenantEvidenceSelectorProviderV1,
    AuthenticatedOwnerTenantScopeObservationProviderV1,
    OwnerTenantAuthorityArtifactBindingV1,
    OwnerTenantEvidenceReadBindingV1,
)


@dataclass(frozen=True, slots=True)
class OwnerTenantAuthorityV1Writers:
    """Bound root and successor writers sharing one repository alias."""

    issue: IssueOwnerTenantAuthorityV1
    supersede: SupersedeOwnerTenantAuthorityV1


def build_owner_tenant_authority_v1_reader(
    *, using: str = "default"
) -> GetCurrentOwnerTenantAuthorityV1:
    """Build the exact-current authority reader for one Django alias."""

    return GetCurrentOwnerTenantAuthorityV1(
        DjangoOwnerTenantAuthorityV1Repository(using=using),
        assignment_reader=build_current_account_owner_assignment_evidence_v3(using=using),
    )


def build_owner_tenant_authority_v1_writers(
    *,
    approver_provider: CurrentOwnerTenantAuthorityApproverProvider,
    validity_period: timedelta,
    using: str = "default",
) -> OwnerTenantAuthorityV1Writers:
    """Build controlled writers; callers must supply current authenticated approval."""

    if approver_provider is None:
        raise TypeError("approver_provider is required")
    repository = DjangoOwnerTenantAuthorityV1Repository(using=using)
    assignments = build_current_account_owner_assignment_evidence_v3(using=using)
    return OwnerTenantAuthorityV1Writers(
        issue=IssueOwnerTenantAuthorityV1(
            assignments=assignments,
            approvers=approver_provider,
            repository=repository,
            validity_period=validity_period,
        ),
        supersede=SupersedeOwnerTenantAuthorityV1(
            assignments=assignments,
            approvers=approver_provider,
            repository=repository,
            validity_period=validity_period,
        ),
    )


def build_authenticated_owner_scoped_evidence_read_facade(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader,
    binding: OwnerTenantEvidenceReadBindingV1,
    using: str = "default",
) -> ScopedEvidenceReadFacade:
    """Compose principal, owner/tenant authority, scope source, and Evidence reads."""

    authority_repository = DjangoOwnerTenantAuthorityV1Repository(using=using)
    selector = AuthenticatedOwnerTenantEvidenceSelectorProviderV1(
        principal=principal,
        actor_authority_reader=actor_authority_reader,
        owner_tenant_reader=GetCurrentOwnerTenantAuthorityV1(
            authority_repository,
            assignment_reader=build_current_account_owner_assignment_evidence_v3(using=using),
        ),
        binding=binding,
        using=using,
    )
    if selector.unit_of_work_key != authority_repository.unit_of_work_key:
        raise ValueError("owner/tenant authority and Evidence selector aliases differ")
    return make_authorized_evidence_read_facade(
        selector_provider=selector,
        using=using,
    )


def build_authenticated_owner_scoped_evidence_scope_issuer(
    *,
    principal: AuthenticatedAccountPrincipalV3,
    actor_authority_reader: ExactCurrentAccountActorAuthorityV3Reader,
    binding: OwnerTenantAuthorityArtifactBindingV1,
    validity_period: timedelta,
    using: str = "default",
) -> AuthenticatedOwnerTenantEvidenceScopeIssuerV1:
    """Build automatic scope capture from current authenticated authority."""

    authority_repository = DjangoOwnerTenantAuthorityV1Repository(using=using)
    observations = AuthenticatedOwnerTenantScopeObservationProviderV1(
        principal=principal,
        actor_authority_reader=actor_authority_reader,
        owner_tenant_reader=GetCurrentOwnerTenantAuthorityV1(
            authority_repository,
            assignment_reader=build_current_account_owner_assignment_evidence_v3(using=using),
        ),
        binding=binding,
        using=using,
    )
    from apps.research.infrastructure.evidence_scope_source_v1_repository import (
        _build_evidence_scope_source_v1_store,
    )

    repository = _build_evidence_scope_source_v1_store(using=using)
    return AuthenticatedOwnerTenantEvidenceScopeIssuerV1(
        observation_provider=observations,
        repository=repository,
        validity_period=validity_period,
    )


__all__ = [
    "OwnerTenantAuthorityV1Writers",
    "build_authenticated_owner_scoped_evidence_scope_issuer",
    "build_authenticated_owner_scoped_evidence_read_facade",
    "build_owner_tenant_authority_v1_reader",
    "build_owner_tenant_authority_v1_writers",
]
