"""Application ports and use cases for ingestion and publication control."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
    QuarantineRecord,
    SyncBatch,
    SyncCheckpoint,
    SyncRun,
)


class SyncRunRepositoryPort(Protocol):
    """Persistence port for sync runs."""

    def save(self, run: SyncRun) -> SyncRun: ...

    def get(self, run_id: str) -> SyncRun | None: ...


class SyncBatchRepositoryPort(Protocol):
    """Persistence port for bounded sync batches."""

    def save(self, batch: SyncBatch) -> SyncBatch: ...


class SyncCheckpointRepositoryPort(Protocol):
    """Persistence port for resumable cursors."""

    def save(self, checkpoint: SyncCheckpoint) -> SyncCheckpoint: ...


class QuarantineRepositoryPort(Protocol):
    """Persistence port for rejected records."""

    def add(self, record: QuarantineRecord) -> QuarantineRecord: ...


class CanonicalPublicationRepositoryPort(Protocol):
    """Persistence port for publication decisions."""

    def save(self, publication: CanonicalPublication) -> CanonicalPublication: ...

    def publish(self, publication: CanonicalPublication) -> CanonicalPublication: ...

    def publish_with_members(
        self,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> CanonicalPublication: ...

    def add_member(self, member: PublicationMember) -> PublicationMember: ...

    def list_members(self, publication_id: str) -> list[PublicationMember]: ...

    def get_oldest_member_observed_at(self, publication_id: str) -> datetime | None: ...

    def get_current(
        self, dataset_key: str, publication_key: str
    ) -> CanonicalPublication | None: ...

    def get_as_of(
        self,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> CanonicalPublication | None: ...


class StartSyncRunUseCase:
    """Start one explicit run and persist its business-level identity."""

    def __init__(self, repository: SyncRunRepositoryPort) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        dataset_key: str,
        trigger: str,
        requested: int,
        provider_name: str = "",
        contract_version: str = "",
        config_snapshot_hash: str = "",
    ) -> SyncRun:
        """Create a requested run with a stable UUID and fail-closed outcome."""

        run = SyncRun(
            run_id=str(uuid4()),
            dataset_key=dataset_key,
            trigger=trigger,
            requested=requested,
            provider_name=provider_name,
            contract_version=contract_version,
            config_snapshot_hash=config_snapshot_hash,
            started_at=datetime.now(UTC),
        )
        return self._repository.save(run)


class RecordQuarantineUseCase:
    """Persist a rejected row without allowing it to enter publication."""

    def __init__(self, repository: QuarantineRepositoryPort) -> None:
        self._repository = repository

    def execute(self, record: QuarantineRecord) -> QuarantineRecord:
        """Store and return the immutable quarantine evidence."""

        return self._repository.add(record)


class PublishCanonicalDatasetUseCase:
    """Apply a publication policy before exposing selected facts as current."""

    def __init__(self, repository: CanonicalPublicationRepositoryPort) -> None:
        self._repository = repository

    def execute(
        self,
        publication: CanonicalPublication,
        *,
        policy: PublicationPolicy,
        members: tuple[PublicationMember, ...] = (),
    ) -> CanonicalPublication:
        """Validate policy, persist members, and publish atomically via the port."""

        if publication.dataset_key != policy.dataset.value:
            raise ValueError("Publication dataset_key does not match policy")
        if publication.coverage.coverage_ratio < policy.minimum_coverage_ratio:
            raise ValueError("Publication coverage is below policy threshold")
        if publication.conflict_count > 0 and policy.conflict_action == "block":
            raise ValueError("Publication contains conflicts blocked by policy")
        if publication.must_not_use_for_decision:
            raise ValueError("Blocked publication cannot be published")
        if publication.coverage.publication_id != publication.publication_id:
            raise ValueError("Publication coverage must reference the same publication")
        if publication.coverage.selected_count != publication.member_count:
            raise ValueError("Publication member_count must match selected coverage count")
        if publication.as_of is None:
            raise ValueError("Published publication requires an explicit as_of boundary")
        if publication.published_at is None:
            raise ValueError("Published publication requires published_at")
        if publication.as_of > publication.published_at:
            raise ValueError("Publication as_of cannot be later than published_at")
        if len(members) != publication.member_count:
            raise ValueError("Publication member_count does not match supplied members")

        natural_keys = [member.natural_key for member in members]
        if len(set(natural_keys)) != len(natural_keys):
            raise ValueError("Publication members must have unique natural_key values")
        member_ids = [member.member_id for member in members]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("Publication members must have unique member_id values")
        fact_refs = [(member.fact_table, member.fact_pk) for member in members]
        if len(set(fact_refs)) != len(fact_refs):
            raise ValueError("Publication members must reference unique canonical facts")
        for member in members:
            if member.dataset_key != publication.dataset_key:
                raise ValueError("Publication member dataset_key mismatch")
            if member.publication_id != publication.publication_id:
                raise ValueError("Publication member publication_id mismatch")
            if member.observed_at is None:
                raise ValueError("Published publication members require observed_at")
            if member.observed_at > publication.as_of:
                raise ValueError("Publication member observed_at exceeds publication as_of")
        if publication.state is not PublicationState.PUBLISHED:
            raise ValueError("Publication must be in published state before committing")
        return self._repository.publish_with_members(publication, tuple(members))


__all__ = [
    "CanonicalPublicationRepositoryPort",
    "PublishCanonicalDatasetUseCase",
    "QuarantineRepositoryPort",
    "RecordQuarantineUseCase",
    "StartSyncRunUseCase",
    "SyncBatchRepositoryPort",
    "SyncCheckpointRepositoryPort",
    "SyncRunRepositoryPort",
]
