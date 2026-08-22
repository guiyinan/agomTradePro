"""Composition roots for canonical Research Evidence reads.

The default owner-scoped composition remains fail-closed.  A later Account or
tenant authority root may inject a selector provider through the explicit
authorized factory; neither factory derives authority from a request or
mutable Django rows.
"""

from __future__ import annotations

from datetime import datetime

from apps.research.application.evidence_reads import ScopedEvidenceReadFacade
from apps.research.application.evidence_scope import (
    EvidenceScopeAuthorizer,
    EvidenceScopeGrant,
)
from apps.research.application.evidence_scope_source_v1 import (
    GetCurrentEvidenceScopeSourceV1,
)
from apps.research.application.evidence_scope_source_v1_provider import (
    EvidenceScopeSourceV1Provider,
    EvidenceScopeSourceV1SelectorProvider,
)
from apps.research.domain.evidence_contracts import ArtifactRef


class _UnwiredEvidenceScopeProvider:
    """Return no grant until an immutable owner/tenant source is composed."""

    def get_current_scope(
        self,
        *,
        artifact: ArtifactRef,
        as_of: datetime,
    ) -> EvidenceScopeGrant | None:
        """Refuse every scope request without touching mutable request state."""

        del artifact, as_of
        return None


def make_evidence_read_facade(*, using: str = "default") -> ScopedEvidenceReadFacade:
    """Build the default reader with authority fail-closed.

    The Evidence repository is constructed on the requested alias, but no
    selector issuer is installed.  Therefore a missing owner/tenant authority
    stops before the repository is queried.
    """

    from apps.research.infrastructure.evidence_repository import DjangoEvidenceRepository

    return ScopedEvidenceReadFacade(
        DjangoEvidenceRepository(using=using),
        scope_authorizer=EvidenceScopeAuthorizer(_UnwiredEvidenceScopeProvider()),
    )


def make_authorized_evidence_read_facade(
    *,
    selector_provider: EvidenceScopeSourceV1SelectorProvider,
    using: str = "default",
) -> ScopedEvidenceReadFacade:
    """Compose a reader from an injected immutable source selector provider.

    The scope-source and Evidence repositories share the same database alias.
    The injected provider must issue an exact server-owned source selector;
    this function does not inspect requests, sessions, users, tenant tables,
    or mutable profiles and does not create authority facts.
    """

    if selector_provider is None:
        raise TypeError("selector_provider is required")
    from apps.research.infrastructure.evidence_repository import DjangoEvidenceRepository
    from apps.research.infrastructure.evidence_scope_source_v1_repository import (
        DjangoEvidenceScopeSourceV1Repository,
    )

    scope_repository = DjangoEvidenceScopeSourceV1Repository(using=using)
    scope_reader = GetCurrentEvidenceScopeSourceV1(scope_repository)
    scope_provider = EvidenceScopeSourceV1Provider(
        reader=scope_reader,
        selectors=selector_provider,
    )
    return ScopedEvidenceReadFacade(
        DjangoEvidenceRepository(using=using),
        scope_authorizer=EvidenceScopeAuthorizer(scope_provider),
    )


__all__ = [
    "make_authorized_evidence_read_facade",
    "make_evidence_read_facade",
]
