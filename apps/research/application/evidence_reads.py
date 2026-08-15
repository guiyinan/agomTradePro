"""Read-only Application facade for exact Research evidence lookups."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.research.application.evidence_scope import (
    EvidenceScopeAuthorizer,
    EvidenceScopeCorruption,
    EvidenceScopeUnavailable,
)
from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    TrackRecordSnapshot,
)


class EvidenceReadRepository(Protocol):
    """Port for content-addressed point-in-time evidence reads."""

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Return one exact Operator Spec knowable at ``as_of``."""

        ...

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Return one exact Track Record knowable at ``as_of``."""

        ...

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Return one exact output-version Envelope knowable at ``as_of``."""

        ...


class EvidenceReadFacade:
    """Expose exact evidence reads without leaking Infrastructure concerns."""

    __slots__ = ("_repository", "_scope_authorizer")

    def __init__(
        self,
        repository: EvidenceReadRepository,
        *,
        scope_authorizer: EvidenceScopeAuthorizer | None = None,
    ) -> None:
        """Create an exact-read facade with an optional fail-closed scope gate.

        The unconfigured form preserves the existing staff-only compatibility
        read path.  When supplied, the authorizer must obtain an exact current
        grant from its trusted provider before any repository call.  No
        caller-supplied tenant or owner value enters this facade.
        """

        self._repository = repository
        self._scope_authorizer = scope_authorizer

    def get_operator_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        """Read one exact Operator Spec through the repository port."""

        if not self._scope_allows(
            artifact=ArtifactRef(
                owner="research",
                artifact_type="evidence_operator_spec",
                artifact_id=operator_id,
                artifact_version=operator_version,
                content_hash=expected_content_hash,
            ),
            as_of=as_of,
        ):
            return None
        return self._repository.get_operator_spec(
            operator_id=operator_id,
            operator_version=operator_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def get_track_record(
        self,
        *,
        snapshot_id: str,
        snapshot_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> TrackRecordSnapshot | None:
        """Read one exact Track Record through the repository port."""

        if not self._scope_allows(
            artifact=ArtifactRef(
                owner="research",
                artifact_type="track_record_snapshot",
                artifact_id=snapshot_id,
                artifact_version=snapshot_version,
                content_hash=expected_content_hash,
            ),
            as_of=as_of,
        ):
            return None
        return self._repository.get_track_record(
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def get_envelope(
        self,
        *,
        output_owner: str,
        output_artifact_type: str,
        output_artifact_id: str,
        output_artifact_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> EvidenceEnvelope | None:
        """Read one exact output-version Envelope through the repository port."""

        if not self._scope_allows(
            artifact=ArtifactRef(
                owner=output_owner,
                artifact_type=output_artifact_type,
                artifact_id=output_artifact_id,
                artifact_version=output_artifact_version,
                content_hash=expected_content_hash,
            ),
            as_of=as_of,
        ):
            return None
        return self._repository.get_envelope(
            output_owner=output_owner,
            output_artifact_type=output_artifact_type,
            output_artifact_id=output_artifact_id,
            output_artifact_version=output_artifact_version,
            expected_content_hash=expected_content_hash,
            as_of=as_of,
        )

    def _scope_allows(self, *, artifact: ArtifactRef, as_of: datetime) -> bool:
        """Return true only when the optional trusted scope gate allows."""

        authorizer = self._scope_authorizer
        if authorizer is None:
            return True
        try:
            authorizer.require(artifact=artifact, as_of=as_of)
        except (EvidenceScopeUnavailable, EvidenceScopeCorruption, TypeError, ValueError):
            return False
        return True


class ScopedEvidenceReadFacade(EvidenceReadFacade):
    """Owner/tenant-scoped exact-read facade with a mandatory authorizer.

    The legacy ``EvidenceReadFacade`` remains available for the existing
    staff-only compatibility surface.  New owner-scoped composition must use
    this class so omitting the scope provider is impossible at construction.
    """

    __slots__ = ()

    def __init__(
        self,
        repository: EvidenceReadRepository,
        *,
        scope_authorizer: EvidenceScopeAuthorizer,
    ) -> None:
        """Create a facade that cannot perform an unscoped repository read."""

        if type(scope_authorizer) is not EvidenceScopeAuthorizer:
            raise TypeError("scope_authorizer must be an exact EvidenceScopeAuthorizer")
        super().__init__(repository, scope_authorizer=scope_authorizer)


__all__ = ["EvidenceReadFacade", "EvidenceReadRepository", "ScopedEvidenceReadFacade"]
