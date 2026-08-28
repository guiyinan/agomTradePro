"""Application ports and use cases for ingestion and publication control."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataPublicationRollbackAuditWriter,
)
from apps.data_center.domain.contracts import PublicationPolicy
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationRollback,
    PublicationState,
    QuarantineRecord,
    SyncBatch,
    SyncCheckpoint,
    SyncRun,
)
from core.integration.data_center_audit import (
    AuditOutcome,
    DataPublicationRollbackAuditObservation,
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

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity used by this repository."""

    def save(self, publication: CanonicalPublication) -> CanonicalPublication: ...

    def publish(self, publication: CanonicalPublication) -> CanonicalPublication: ...

    def publish_with_members(
        self,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> CanonicalPublication: ...

    def add_member(self, member: PublicationMember) -> PublicationMember: ...

    def list_members(self, publication_id: str) -> list[PublicationMember]: ...

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        """Return one exact publication identity or ``None``."""

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

    def rollback(self, rollback: PublicationRollback) -> CanonicalPublication: ...

    def get_rollback_by_id(self, rollback_id: str) -> PublicationRollback | None:
        """Return one exact durable rollback evidence row or ``None``."""


def publication_rollback_evidence_content_hash(evidence: PublicationRollback) -> str:
    """Hash the exact persisted rollback evidence using canonical JSON."""

    if not isinstance(evidence, PublicationRollback):
        raise TypeError("evidence must be a PublicationRollback")
    if not evidence.rollback_id:
        raise ValueError("persisted rollback evidence requires rollback_id")
    if not evidence.previous_publication_id:
        raise ValueError("persisted rollback evidence requires previous_publication_id")
    payload: dict[str, object] = {
        "rollback_id": evidence.rollback_id,
        "target_publication_id": evidence.target_publication_id,
        "previous_publication_id": evidence.previous_publication_id,
        "reason": evidence.reason,
        "operator": evidence.operator,
        "observed_at": evidence.observed_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


class RollbackCanonicalPublicationUseCase:
    """Restore a prior publication only with explicit operator evidence."""

    def __init__(
        self,
        repository: CanonicalPublicationRepositoryPort,
        *,
        audit_writer: DataPublicationRollbackAuditWriter,
        unit_of_work: DataCenterSyncUnitOfWork,
        clock: DataCenterSyncClock,
    ) -> None:
        if repository.unit_of_work_key != unit_of_work.unit_of_work_key:
            raise ValueError("publication repository and rollback unit of work differ")
        self._repository = repository
        self._audit_writer = audit_writer
        self._unit_of_work = unit_of_work
        self._clock = clock

    @property
    def database_alias(self) -> str:
        """Return the database alias used by the canonical audit writer."""

        return self._audit_writer.database_alias

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity for the rollback commit."""

        return self._unit_of_work.unit_of_work_key

    def execute(
        self,
        *,
        target_publication_id: str,
        reason: str,
        operator: str,
        observed_at: datetime,
        rollback_id: str | None = None,
    ) -> CanonicalPublication:
        """Restore a snapshot and append exact rollback audit in one transaction."""

        recorded_at = self._clock.now()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("publication rollback clock must be timezone-aware")
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("publication rollback observed_at must be timezone-aware")
        if observed_at > recorded_at:
            raise ValueError("publication rollback observed_at cannot be after recorded_at")
        rollback_identity = rollback_id or str(uuid4())
        rollback = PublicationRollback(
            target_publication_id=target_publication_id,
            reason=reason,
            operator=operator,
            observed_at=observed_at,
            rollback_id=rollback_identity,
        )
        with self._unit_of_work.atomic():
            restored = self._repository.rollback(rollback)
            evidence = self._repository.get_rollback_by_id(rollback_identity)
            if evidence is None:
                raise ValueError("publication rollback evidence was not persisted")
            if (
                evidence.rollback_id != rollback_identity
                or evidence.target_publication_id != target_publication_id
                or evidence.reason != reason
                or evidence.operator != operator
                or evidence.observed_at != observed_at
                or not evidence.previous_publication_id
            ):
                raise ValueError("publication rollback evidence was substituted")
            if (
                restored.publication_id != target_publication_id
                or restored.state is not PublicationState.PUBLISHED
                or restored.reinstated_at != observed_at
            ):
                raise ValueError("publication rollback result was substituted")
            previous = self._repository.get_by_id(evidence.previous_publication_id)
            if previous is None:
                raise ValueError("previous publication evidence is unavailable")
            if (
                previous.dataset_key != restored.dataset_key
                or previous.publication_key != restored.publication_key
                or previous.state is not PublicationState.SUPERSEDED
                or previous.superseded_at != observed_at
            ):
                raise ValueError("previous publication evidence is inconsistent")
            self._audit_writer.write(
                DataPublicationRollbackAuditObservation(
                    dataset_key=restored.dataset_key,
                    publication_key=restored.publication_key,
                    publication_id=restored.publication_id,
                    publication_version=restored.policy_version,
                    publication_hash=restored.publication_hash,
                    rollback_id=evidence.rollback_id,
                    rollback_version="1",
                    rollback_content_hash=publication_rollback_evidence_content_hash(evidence),
                    previous_publication_id=previous.publication_id,
                    previous_publication_version=previous.policy_version,
                    previous_publication_hash=previous.publication_hash,
                    run_id=restored.run_id,
                    occurred_at=evidence.observed_at,
                    recorded_at=recorded_at,
                    outcome=AuditOutcome.ROLLED_BACK,
                )
            )
        return restored


__all__ = [
    "CanonicalPublicationRepositoryPort",
    "PublishCanonicalDatasetUseCase",
    "RollbackCanonicalPublicationUseCase",
    "publication_rollback_evidence_content_hash",
    "QuarantineRepositoryPort",
    "RecordQuarantineUseCase",
    "StartSyncRunUseCase",
    "SyncBatchRepositoryPort",
    "SyncCheckpointRepositoryPort",
    "SyncRunRepositoryPort",
]
