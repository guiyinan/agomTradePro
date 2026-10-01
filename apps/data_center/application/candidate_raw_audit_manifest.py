"""Use cases for staging and checking candidate-level RawAudit manifests."""

from __future__ import annotations

from typing import Protocol

from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
)


class CandidateRawAuditManifestRepositoryProtocol(Protocol):
    """Persistence contract for immutable candidate RawAudit manifests."""

    def stage(self, manifest: CandidateRawAuditManifest) -> CandidateRawAuditManifest:
        """Persist a complete manifest for an exact publication candidate."""

    def get_by_publication_id(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Read one stored manifest without substituting another publication."""

    def validate(self, publication_id: str) -> CandidateRawAuditManifest:
        """Re-read publication and all RawAudit rows and fail on any drift."""


class CandidateRawAuditManifestService:
    """Stage, read, and validate exact multi-batch publication lineage."""

    def __init__(self, repository: CandidateRawAuditManifestRepositoryProtocol) -> None:
        """Bind the use case to a repository implementation."""

        self._repository = repository

    def stage(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        run_id: str,
        dataset_key: str,
        publication_key: str,
        task_attempt_id: str,
        raw_audits: tuple[CandidateRawAuditReference, ...],
        manifest_id: str | None = None,
    ) -> CandidateRawAuditManifest:
        """Build and persist a manifest, requiring the caller's task-attempt identity."""

        manifest = CandidateRawAuditManifest.create(
            publication_id=publication_id,
            publication_hash=publication_hash,
            run_id=run_id,
            dataset_key=dataset_key,
            publication_key=publication_key,
            task_attempt_id=task_attempt_id,
            raw_audits=raw_audits,
            manifest_id=manifest_id,
        )
        return self._repository.stage(manifest)

    def read(self, publication_id: str) -> CandidateRawAuditManifest | None:
        """Return the manifest header and all children for one publication."""

        return self._repository.get_by_publication_id(publication_id)

    def validate(self, publication_id: str) -> CandidateRawAuditManifest:
        """Re-read and verify the full manifest lineage before downstream use."""

        return self._repository.validate(publication_id)


__all__ = [
    "CandidateRawAuditManifestRepositoryProtocol",
    "CandidateRawAuditManifestService",
]
