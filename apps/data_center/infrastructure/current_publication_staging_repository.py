"""Atomic persistence for current-publication candidate staging bundles."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.data_center.application.candidate_raw_audit_manifest import (
    CandidateRawAuditManifestRepositoryProtocol,
)
from apps.data_center.application.control_plane import CanonicalPublicationRepositoryPort
from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationCandidateSnapshot,
)
from apps.data_center.application.current_publication_staging import (
    CandidateRawAuditSourceType,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStagingRepositoryProtocol,
)
from apps.data_center.application.publication_utils import publication_member_manifest_hash
from apps.data_center.domain.control_plane import PublicationMember, PublicationState
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
)

from .candidate_raw_audit_manifest_repository import DjangoCandidateRawAuditManifestRepository
from .control_plane_repositories import CanonicalPublicationRepository
from .publication_member_store import publication_fact_content_hashes_and_ingested_runs
from .publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)

_MEMBER_INSERT_BATCH_SIZE = 500
_DEFAULT_ALIAS = "default"


class DjangoCurrentPublicationStagingRepository(CurrentPublicationStagingRepositoryProtocol):
    """Stage a candidate, members, seal, and RawAudit manifest in one database UOW."""

    def __init__(
        self,
        *,
        using: str = _DEFAULT_ALIAS,
        publication_repository: CanonicalPublicationRepositoryPort | None = None,
        manifest_repository: CandidateRawAuditManifestRepositoryProtocol | None = None,
    ) -> None:
        """Bind all stage writes to the same default database transaction."""

        if using != _DEFAULT_ALIAS:
            raise ValueError("current publication staging currently requires the default database")
        self._using = using
        self._publications = publication_repository or CanonicalPublicationRepository()
        self._manifests = manifest_repository or DjangoCandidateRawAuditManifestRepository(
            using=using
        )
        if self._publications.unit_of_work_key != f"django:{using}":
            raise ValueError("current publication staging repository database alias differs")
        manifest_alias = getattr(self._manifests, "database_alias", using)
        if manifest_alias != using:
            raise ValueError("current publication staging manifest database alias differs")

    @property
    def database_alias(self) -> str:
        """Return the fixed alias shared by all staging persistence ports."""

        return self._using

    @transaction.atomic
    def stage(
        self,
        candidate: CurrentPublicationCandidateSnapshot,
        manifest: CandidateRawAuditManifest,
        source_types: tuple[CandidateRawAuditSourceType, ...],
    ) -> CurrentPublicationStagedCandidate:
        """Persist the complete immutable candidate bundle or roll every row back."""

        publication = candidate.publication
        self._validate_bundle_identity(candidate, manifest)
        source_type_map = _source_type_map(source_types)
        candidate_id = UUID(publication.publication_id)
        existing = (
            CanonicalPublicationModel._default_manager.select_for_update()
            .filter(publication_id=candidate_id)
            .first()
        )
        if existing is not None:
            staged = self._replay_existing(
                existing=existing,
                candidate=candidate,
                manifest=manifest,
                source_type_map=source_type_map,
            )
            self._ensure_scope_pointer(candidate)
            return staged

        if PublicationMemberModel._default_manager.filter(publication_id=candidate_id).exists():
            raise CandidateRawAuditManifestError(
                "orphan candidate members prevent safe publication staging"
            )
        self._ensure_scope_pointer(candidate)
        self._publications.save(publication)
        self._persist_members(candidate.members)
        persisted_members = tuple(self._publications.list_members(publication.publication_id))
        if persisted_members != candidate.members:
            raise CandidateRawAuditManifestError(
                "persisted candidate members differ from the selected snapshot"
            )
        self._validate_fact_lineage(candidate, manifest, source_type_map)
        self._seal_candidate(candidate, persisted_members)
        staged_manifest = self._manifests.stage(manifest)
        persisted_publication = self._publications.get_by_id(publication.publication_id)
        if (
            persisted_publication is None
            or persisted_publication.state is not PublicationState.CANDIDATE
        ):
            raise CandidateRawAuditManifestError("staged publication candidate disappeared")
        return CurrentPublicationStagedCandidate(
            publication=persisted_publication,
            manifest=staged_manifest,
        )

    @staticmethod
    def _ensure_scope_pointer(candidate: CurrentPublicationCandidateSnapshot) -> None:
        """Create a lockable empty scope pointer without changing an existing current target."""

        publication = candidate.publication
        (
            pointer,
            _created,
        ) = CanonicalPublicationPointerModel._default_manager.select_for_update().get_or_create(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            defaults={
                "publication_id": None,
                "publication_hash": "",
                "activation_id": "",
            },
        )
        if pointer.publication_id is None:
            if pointer.publication_hash or pointer.activation_id:
                raise CandidateRawAuditManifestError(
                    "empty current publication pointer contains stale activation identity"
                )
        elif pointer.publication_id == UUID(publication.publication_id):
            raise CandidateRawAuditManifestError(
                "candidate staging cannot make its publication the current pointer target"
            )

    def _persist_members(self, members: tuple[PublicationMember, ...]) -> None:
        """Bulk insert all deterministic member rows within the stage transaction."""

        rows = [
            PublicationMemberModel(
                member_id=UUID(member.member_id),
                publication_id=UUID(member.publication_id),
                dataset_key=member.dataset_key,
                natural_key=member.natural_key,
                source=member.source,
                source_record_id=member.source_record_id,
                fact_table=member.fact_table,
                fact_pk=member.fact_pk,
                observed_at=member.observed_at,
                raw_payload_hash=member.raw_payload_hash,
                quality_status=member.quality_status,
                revision_number=member.revision_number,
                available_at=member.available_at,
                fetched_at=member.fetched_at,
                source_published_at=member.source_published_at,
                raw_payload_scope=member.raw_payload_scope,
                fact_content_hash=member.fact_content_hash,
            )
            for member in members
        ]
        PublicationMemberModel._default_manager.bulk_create(
            rows,
            batch_size=_MEMBER_INSERT_BATCH_SIZE,
        )

    def _seal_candidate(
        self,
        candidate: CurrentPublicationCandidateSnapshot,
        members: tuple[PublicationMember, ...],
    ) -> None:
        """Persist the same ordered member seal verified by the activation path."""

        manifest_hash = publication_member_manifest_hash(
            members,
            policy_identity=candidate.publication.policy_version,
        )
        updated = CanonicalPublicationModel._default_manager.filter(
            publication_id=UUID(candidate.publication.publication_id),
            state=PublicationState.CANDIDATE.value,
            members_sealed_at__isnull=True,
        ).update(
            member_manifest_hash=manifest_hash,
            members_sealed_at=timezone.now(),
        )
        if updated != 1:
            raise CandidateRawAuditManifestError("candidate member set could not be sealed")

    def _replay_existing(
        self,
        *,
        existing: CanonicalPublicationModel,
        candidate: CurrentPublicationCandidateSnapshot,
        manifest: CandidateRawAuditManifest,
        source_type_map: dict[str, str],
    ) -> CurrentPublicationStagedCandidate:
        """Accept only an exact same-attempt replay of a previously sealed bundle."""

        if existing.state != PublicationState.CANDIDATE.value:
            raise CandidateRawAuditManifestError(
                "existing non-candidate publication cannot be adopted for staging"
            )
        self._assert_persisted_candidate_identity(existing, candidate)
        members = tuple(self._publications.list_members(candidate.publication.publication_id))
        if members != candidate.members:
            raise CandidateRawAuditManifestError("existing candidate members differ from retry")
        expected_seal = publication_member_manifest_hash(
            members,
            policy_identity=candidate.publication.policy_version,
        )
        if existing.members_sealed_at is None or existing.member_manifest_hash != expected_seal:
            raise CandidateRawAuditManifestError(
                "existing candidate member seal is missing or changed"
            )
        self._validate_fact_lineage(candidate, manifest, source_type_map)
        stored_manifest = self._manifests.get_by_publication_id(
            candidate.publication.publication_id
        )
        if stored_manifest is None:
            raise CandidateRawAuditManifestError(
                "existing candidate without a RawAudit manifest cannot be adopted"
            )
        if stored_manifest.task_attempt_id != manifest.task_attempt_id:
            raise CandidateRawAuditManifestError(
                "publication RawAudit manifest retry changed task-attempt identity"
            )
        if stored_manifest.manifest_hash != manifest.manifest_hash:
            raise CandidateRawAuditManifestError(
                "publication already has a different immutable RawAudit manifest"
            )
        validated_manifest = self._manifests.validate(candidate.publication.publication_id)
        persisted_publication = self._publications.get_by_id(candidate.publication.publication_id)
        if persisted_publication is None:
            raise CandidateRawAuditManifestError("existing publication candidate disappeared")
        return CurrentPublicationStagedCandidate(
            publication=persisted_publication,
            manifest=validated_manifest,
        )

    @staticmethod
    def _validate_bundle_identity(
        candidate: CurrentPublicationCandidateSnapshot,
        manifest: CandidateRawAuditManifest,
    ) -> None:
        """Require a manifest to name the exact candidate snapshot being staged."""

        publication = candidate.publication
        if (
            publication.state is not PublicationState.CANDIDATE
            or publication.publication_id != manifest.publication_id
            or publication.publication_hash != manifest.publication_hash
            or publication.dataset_key != manifest.dataset_key
            or publication.publication_key != manifest.publication_key
            or publication.run_id != manifest.run_id
        ):
            raise CandidateRawAuditManifestError(
                "candidate RawAudit manifest identity does not match the candidate"
            )

    @staticmethod
    def _assert_persisted_candidate_identity(
        existing: CanonicalPublicationModel,
        candidate: CurrentPublicationCandidateSnapshot,
    ) -> None:
        """Compare persisted candidate headers to the deterministic retry snapshot."""

        publication = candidate.publication
        if (
            str(existing.publication_id) != publication.publication_id
            or existing.dataset_key != publication.dataset_key
            or existing.publication_key != publication.publication_key
            or existing.policy_version != publication.policy_version
            or existing.publication_hash != publication.publication_hash
            or existing.member_count != publication.member_count
            or existing.conflict_count != publication.conflict_count
            or existing.coverage_requested_count != publication.coverage.requested_count
            or existing.coverage_eligible_count != publication.coverage.eligible_count
            or existing.coverage_selected_count != publication.coverage.selected_count
            or existing.coverage_missing_count != publication.coverage.missing_count
            or existing.coverage_conflict_count != publication.coverage.conflict_count
            or existing.as_of != publication.as_of
            or existing.published_at != publication.published_at
            or str(existing.run_id or "") != publication.run_id
            or existing.scope_blocks != [block.to_dict() for block in publication.scope_blocks]
        ):
            raise CandidateRawAuditManifestError("existing candidate identity differs from retry")

    @staticmethod
    def _validate_fact_lineage(
        candidate: CurrentPublicationCandidateSnapshot,
        manifest: CandidateRawAuditManifest,
        source_type_map: dict[str, str],
    ) -> None:
        """Verify member fact hashes, ingestion ownership, and declared source types."""

        audit_run_ids = {item.ingested_run_id for item in manifest.raw_audits}
        if set(source_type_map) != audit_run_ids:
            raise CandidateRawAuditManifestError(
                "candidate RawAudit source types do not cover exact ingestion identities"
            )
        fact_hashes, fact_ingested_run_ids = publication_fact_content_hashes_and_ingested_runs(
            candidate.members
        )
        observed_audit_ids: set[str] = set()
        for member in candidate.members:
            key = (member.fact_table, member.fact_pk)
            if fact_hashes.get(key) != member.fact_content_hash:
                raise CandidateRawAuditManifestError("candidate fact content hash drifted")
            ingested_run_id = fact_ingested_run_ids.get(key)
            if not ingested_run_id or ingested_run_id not in audit_run_ids:
                raise CandidateRawAuditManifestError(
                    "candidate fact belongs to a foreign or missing ingestion run"
                )
            if source_type_map.get(ingested_run_id) != member.source:
                raise CandidateRawAuditManifestError(
                    "candidate fact source does not match its RawAudit source_type"
                )
            observed_audit_ids.add(ingested_run_id)
        if observed_audit_ids != audit_run_ids:
            raise CandidateRawAuditManifestError(
                "candidate RawAudit manifest contains a foreign ingestion run"
            )


def _source_type_map(source_types: tuple[CandidateRawAuditSourceType, ...]) -> dict[str, str]:
    """Validate and normalize explicit source-type bindings by ingestion identity."""

    if not source_types:
        raise CandidateRawAuditManifestError("candidate RawAudit source types are required")
    result: dict[str, str] = {}
    for item in source_types:
        if not isinstance(item, CandidateRawAuditSourceType):
            raise CandidateRawAuditManifestError("candidate RawAudit source type is invalid")
        prior = result.get(item.ingested_run_id)
        if prior is not None and prior != item.source_type:
            raise CandidateRawAuditManifestError(
                "one ingestion identity resolves to multiple source types"
            )
        result[item.ingested_run_id] = item.source_type
    return result


__all__ = ["DjangoCurrentPublicationStagingRepository"]
