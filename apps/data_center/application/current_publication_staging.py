"""Stage current-publication candidates and their exact RawAudit manifests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.control_plane import CanonicalPublication, PublicationState
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
    CandidateRawAuditReference,
    validate_raw_audit_source_type,
)
from core.exceptions import DataValidationError

from .current_publication_candidate import CurrentPublicationCandidateSnapshot
from .current_publication_rebuild import (
    CurrentPublicationRebuildUseCase,
    CurrentPublicationScopeExclusion,
)


class CurrentPublicationStagingError(DataValidationError):
    """Stable application error for rejected current-publication staging input."""

    default_message = "Current publication candidate staging was rejected"
    default_code = "CURRENT_PUBLICATION_STAGING_INVALID"


@dataclass(frozen=True)
class CurrentPublicationStageRawAuditBinding:
    """Caller-supplied expected source type for one exact persisted audit reference."""

    reference: RawAuditReference
    expected_source_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.reference, RawAuditReference):
            raise CurrentPublicationStagingError(
                "Current publication staging requires RawAuditReference values"
            )
        try:
            validate_raw_audit_source_type(self.expected_source_type)
        except CandidateRawAuditManifestError as error:
            raise CurrentPublicationStagingError(str(error)) from error


@dataclass(frozen=True)
class CurrentPublicationStageCommand:
    """One dataset candidate staging request with explicit lineage and attempt identity."""

    asset_codes: tuple[str, ...]
    published_at: datetime
    run_id: str
    task_attempt_id: str
    raw_audit_bindings: tuple[CurrentPublicationStageRawAuditBinding, ...]
    scope_exclusions: tuple[CurrentPublicationScopeExclusion, ...] = ()
    required_observation_date: date | None = None

    def __post_init__(self) -> None:
        if not self.asset_codes or any(not code.strip() for code in self.asset_codes):
            raise CurrentPublicationStagingError(
                "Current publication staging requires an asset universe"
            )
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise CurrentPublicationStagingError("published_at must be timezone-aware")
        if type(self.run_id) is not str:
            raise CurrentPublicationStagingError(
                "Current publication staging requires a canonical run id"
            )
        try:
            canonical_run_id = str(UUID(self.run_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise CurrentPublicationStagingError(
                "Current publication staging requires a canonical run id"
            ) from error
        if canonical_run_id != self.run_id:
            raise CurrentPublicationStagingError(
                "Current publication staging requires a canonical run id"
            )
        if (
            type(self.task_attempt_id) is not str
            or not self.task_attempt_id
            or len(self.task_attempt_id) > 160
            or any(
                character
                not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:/-"
                for character in self.task_attempt_id
            )
        ):
            raise CurrentPublicationStagingError(
                "task_attempt_id must be a bounded canonical token"
            )
        if not self.raw_audit_bindings or any(
            not isinstance(item, CurrentPublicationStageRawAuditBinding)
            for item in self.raw_audit_bindings
        ):
            raise CurrentPublicationStagingError(
                "Current publication staging requires exact RawAudit bindings"
            )
        raw_ids = tuple(item.reference.raw_audit_id for item in self.raw_audit_bindings)
        if len(raw_ids) != len(set(raw_ids)):
            raise CurrentPublicationStagingError(
                "Current publication RawAudit bindings must be unique"
            )
        if self.required_observation_date is not None and (
            not isinstance(self.required_observation_date, date)
            or isinstance(self.required_observation_date, datetime)
        ):
            raise CurrentPublicationStagingError("required_observation_date must be a date")


@dataclass(frozen=True)
class CandidateRawAuditSourceType:
    """Source-type evidence joined to the exact ingestion identity it describes."""

    ingested_run_id: str
    source_type: str

    def __post_init__(self) -> None:
        try:
            canonical_ingested_run_id = str(UUID(self.ingested_run_id))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(
                "candidate RawAudit source type requires an ingestion identity"
            ) from error
        if canonical_ingested_run_id != self.ingested_run_id:
            raise ValueError("candidate RawAudit source type requires an ingestion identity")
        validate_raw_audit_source_type(self.source_type)


@dataclass(frozen=True)
class CurrentPublicationStagedCandidate:
    """Persisted candidate and its complete immutable RawAudit manifest."""

    publication: CanonicalPublication
    manifest: CandidateRawAuditManifest

    def __post_init__(self) -> None:
        if self.publication.state is not PublicationState.CANDIDATE:
            raise ValueError("Staged current publication must remain CANDIDATE")
        if self.publication.publication_id != self.manifest.publication_id:
            raise ValueError("Staged candidate and RawAudit manifest identities differ")
        if self.publication.publication_hash != self.manifest.publication_hash:
            raise ValueError("Staged candidate and RawAudit manifest hashes differ")


class CandidateRawAuditMetadataResolverProtocol(Protocol):
    """Bulk-validate persisted RawAudit identity and dataset-specific source metadata."""

    def resolve(
        self,
        bindings: tuple[CurrentPublicationStageRawAuditBinding, ...],
        *,
        dataset_key: str,
    ) -> tuple[CandidateRawAuditReference, ...]:
        """Resolve each exact binding in input order or reject the entire set."""


class CurrentPublicationStagingRepositoryProtocol(Protocol):
    """Atomic persistence port for candidate, immutable members, seal, and manifest."""

    def stage(
        self,
        candidate: CurrentPublicationCandidateSnapshot,
        manifest: CandidateRawAuditManifest,
        source_types: tuple[CandidateRawAuditSourceType, ...],
    ) -> CurrentPublicationStagedCandidate:
        """Persist all stage evidence atomically or leave no partial candidate."""


class CurrentPublicationStagingUseCase:
    """Prepare and atomically stage one current-publication candidate bundle."""

    def __init__(
        self,
        *,
        rebuilder: CurrentPublicationRebuildUseCase,
        raw_audit_resolver: CandidateRawAuditMetadataResolverProtocol,
        repository: CurrentPublicationStagingRepositoryProtocol,
    ) -> None:
        self._rebuilder = rebuilder
        self._raw_audit_resolver = raw_audit_resolver
        self._repository = repository

    def execute(self, command: CurrentPublicationStageCommand) -> CurrentPublicationStagedCandidate:
        """Build policy-valid candidate content and bind its exact RawAudit set."""

        if type(command) is not CurrentPublicationStageCommand:
            raise CurrentPublicationStagingError("staging command has an invalid type")
        try:
            candidate = self._rebuilder.prepare_candidate(
                asset_codes=command.asset_codes,
                published_at=command.published_at,
                run_id=command.run_id,
                scope_exclusions=command.scope_exclusions,
                required_observation_date=command.required_observation_date,
            )
            raw_references = self._raw_audit_resolver.resolve(
                command.raw_audit_bindings,
                dataset_key=candidate.publication.dataset_key,
            )
            if len(raw_references) != len(command.raw_audit_bindings):
                raise ValueError("RawAudit resolver returned an incomplete reference set")

            source_types_by_ingested_run_id: dict[str, str] = {}
            for binding, resolved in zip(command.raw_audit_bindings, raw_references, strict=True):
                if (
                    binding.reference.raw_audit_id != resolved.raw_audit_id
                    or binding.reference.content_hash != resolved.content_hash
                    or binding.reference.run_id != resolved.run_id
                    or binding.reference.ingested_run_id != resolved.ingested_run_id
                ):
                    raise ValueError("RawAudit resolver changed a requested reference identity")
                prior_source_type = source_types_by_ingested_run_id.get(resolved.ingested_run_id)
                if (
                    prior_source_type is not None
                    and prior_source_type != binding.expected_source_type
                ):
                    raise ValueError("One ingestion identity resolves to multiple source types")
                source_types_by_ingested_run_id[resolved.ingested_run_id] = (
                    binding.expected_source_type
                )

            manifest = CandidateRawAuditManifest.create(
                publication_id=candidate.publication.publication_id,
                publication_hash=candidate.publication.publication_hash,
                run_id=command.run_id,
                dataset_key=candidate.publication.dataset_key,
                publication_key=candidate.publication.publication_key,
                task_attempt_id=command.task_attempt_id,
                raw_audits=raw_references,
            )
            source_types = tuple(
                CandidateRawAuditSourceType(ingested_run_id=run_id, source_type=source_type)
                for run_id, source_type in sorted(source_types_by_ingested_run_id.items())
            )
            return self._repository.stage(candidate, manifest, source_types)
        except CurrentPublicationStagingError:
            raise
        except (CandidateRawAuditManifestError, TypeError, ValueError) as error:
            raise CurrentPublicationStagingError(str(error)) from error


__all__ = [
    "CandidateRawAuditMetadataResolverProtocol",
    "CandidateRawAuditSourceType",
    "CurrentPublicationStageCommand",
    "CurrentPublicationStageRawAuditBinding",
    "CurrentPublicationStagingError",
    "CurrentPublicationStagedCandidate",
    "CurrentPublicationStagingRepositoryProtocol",
    "CurrentPublicationStagingUseCase",
]
