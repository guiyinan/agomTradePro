"""Fail-closed composition root for canonical Research evidence reads.

The production owner/tenant authority provider is intentionally not wired yet.
Until it exists, this root must still construct the scoped facade so a staff
permission cannot silently become an owner/tenant grant.
"""

from __future__ import annotations

from datetime import datetime

from apps.research.application.evidence_reads import ScopedEvidenceReadFacade
from apps.research.application.evidence_scope import (
    EvidenceScopeAuthorizer,
    EvidenceScopeGrant,
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


def make_evidence_read_facade() -> ScopedEvidenceReadFacade:
    """Inject exact reads behind a mandatory fail-closed scope boundary."""

    from apps.research.infrastructure.evidence_repository import DjangoEvidenceRepository

    return ScopedEvidenceReadFacade(
        DjangoEvidenceRepository(),
        scope_authorizer=EvidenceScopeAuthorizer(_UnwiredEvidenceScopeProvider()),
    )


__all__ = ["make_evidence_read_facade"]
