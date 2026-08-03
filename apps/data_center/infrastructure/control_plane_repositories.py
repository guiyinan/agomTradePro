"""Django repositories for the Data Center ingestion control plane."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from django.db import transaction

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationMember,
    PublicationState,
    QuarantineRecord,
    SyncBatch,
    SyncCheckpoint,
    SyncRun,
)

from .models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    QuarantineRecordModel,
    SyncBatchModel,
    SyncCheckpointModel,
    SyncRunModel,
)


def _uuid(value: str) -> UUID:
    """Convert a domain identifier to a Django UUID."""

    return UUID(value)


class SyncRunRepository:
    """Persist and query business-level sync runs."""

    def save(self, run: SyncRun) -> SyncRun:
        """Create or replace one run by its immutable identifier."""

        model, _ = SyncRunModel._default_manager.update_or_create(
            run_id=_uuid(run.run_id),
            defaults={
                "dataset_key": run.dataset_key,
                "trigger": run.trigger,
                "status": run.status.value,
                "outcome": run.outcome,
                "provider_name": run.provider_name,
                "contract_version": run.contract_version,
                "config_snapshot_hash": run.config_snapshot_hash,
                "requested": run.requested,
                "fetched": run.fetched,
                "validated": run.validated,
                "quarantined": run.quarantined,
                "succeeded": run.succeeded,
                "failed": run.failed,
                "stored": run.stored,
                "published": run.published,
                "unchanged": run.unchanged,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "error_code": run.error_code,
                "error_message": run.error_message,
            },
        )
        return model.to_domain()

    def get(self, run_id: str) -> SyncRun | None:
        """Return one run or ``None`` when it does not exist."""

        model = SyncRunModel._default_manager.filter(run_id=_uuid(run_id)).first()
        return model.to_domain() if model is not None else None

    def list_recent(self, *, dataset_key: str | None = None, limit: int = 100) -> list[SyncRun]:
        """Return bounded newest runs for operational views."""

        queryset = SyncRunModel._default_manager.all()
        if dataset_key:
            queryset = queryset.filter(dataset_key=dataset_key)
        return [model.to_domain() for model in queryset.order_by("-started_at")[:limit]]


class SyncBatchRepository:
    """Idempotent persistence for bounded sync batches."""

    def save(self, batch: SyncBatch) -> SyncBatch:
        """Upsert a batch by its stable idempotency key."""

        model, _ = SyncBatchModel._default_manager.update_or_create(
            idempotency_key=batch.idempotency_key,
            defaults={
                "batch_id": _uuid(batch.batch_id),
                "run_id": _uuid(batch.run_id),
                "dataset_key": batch.dataset_key,
                "provider_name": batch.provider_name,
                "state": batch.state.value,
                "requested": batch.requested,
                "fetched": batch.fetched,
                "validated": batch.validated,
                "quarantined": batch.quarantined,
                "succeeded": batch.succeeded,
                "failed": batch.failed,
                "stored": batch.stored,
                "published": batch.published,
                "window_start": batch.window_start,
                "window_end": batch.window_end,
                "started_at": batch.started_at,
                "finished_at": batch.finished_at,
                "error_code": batch.error_code,
                "error_message": batch.error_message,
            },
        )
        return model.to_domain()

    def get_by_idempotency_key(self, idempotency_key: str) -> SyncBatch | None:
        """Return an existing batch for retry/resume handling."""

        model = SyncBatchModel._default_manager.filter(idempotency_key=idempotency_key).first()
        return model.to_domain() if model is not None else None

    def list_for_run(self, run_id: str) -> list[SyncBatch]:
        """Return all bounded batches for one run."""

        return [
            model.to_domain()
            for model in SyncBatchModel._default_manager.filter(run_id=_uuid(run_id)).order_by(
                "created_at"
            )
        ]


class SyncCheckpointRepository:
    """Durable cursor repository used by resumable sync tasks."""

    def save(self, checkpoint: SyncCheckpoint) -> SyncCheckpoint:
        """Upsert a checkpoint by batch/cursor identity."""

        model, _ = SyncCheckpointModel._default_manager.update_or_create(
            batch_id=_uuid(checkpoint.batch_id),
            cursor_name=checkpoint.cursor_name,
            cursor_value=checkpoint.cursor_value,
            defaults={
                "checkpoint_id": _uuid(checkpoint.checkpoint_id),
                "run_id": _uuid(checkpoint.run_id),
                "state": checkpoint.state.value,
                "processed": checkpoint.processed,
                "failed": checkpoint.failed,
                "recorded_at": checkpoint.recorded_at,
                "error_code": checkpoint.error_code,
            },
        )
        return model.to_domain()

    def latest_for_batch(self, batch_id: str) -> SyncCheckpoint | None:
        """Return the newest checkpoint for a batch."""

        model = (
            SyncCheckpointModel._default_manager.filter(batch_id=_uuid(batch_id))
            .order_by("-recorded_at")
            .first()
        )
        return model.to_domain() if model is not None else None


class QuarantineRepository:
    """Append-only rejected-payload repository."""

    def add(self, record: QuarantineRecord) -> QuarantineRecord:
        """Persist one quarantine record without overwriting prior evidence."""

        model = QuarantineRecordModel._default_manager.create(
            quarantine_id=_uuid(record.quarantine_id),
            dataset_key=record.dataset_key,
            provider_name=record.provider_name,
            natural_key=record.natural_key,
            reason_code=record.reason_code,
            reason=record.reason,
            payload_hash=record.payload_hash,
            schema_fingerprint=record.schema_fingerprint,
            payload=record.payload,
            observed_at=record.observed_at,
            run_id=_uuid(record.run_id) if record.run_id else None,
            batch_id=_uuid(record.batch_id) if record.batch_id else None,
            resolution=record.resolution.value,
            quarantined_at=record.quarantined_at,
            resolved_at=record.resolved_at,
            resolved_by=record.resolved_by,
        )
        return model.to_domain()

    def list_open(
        self, *, dataset_key: str | None = None, limit: int = 100
    ) -> list[QuarantineRecord]:
        """Return open quarantine records for operator remediation."""

        queryset = QuarantineRecordModel._default_manager.filter(resolution="open")
        if dataset_key:
            queryset = queryset.filter(dataset_key=dataset_key)
        return [model.to_domain() for model in queryset.order_by("-quarantined_at")[:limit]]


class CanonicalPublicationRepository:
    """Persist publication decisions and selected fact references."""

    def save(self, publication: CanonicalPublication) -> CanonicalPublication:
        """Save a publication and its immutable coverage snapshot atomically.

        A published row is never written without its selected member set.  The
        staged ``publish_with_members`` path writes candidates first and only
        calls this method after the member count has been verified.
        """

        if publication.state is PublicationState.PUBLISHED:
            persisted_count = PublicationMemberModel._default_manager.filter(
                publication_id=_uuid(publication.publication_id)
            ).count()
            if persisted_count != publication.member_count:
                raise ValueError("Published publication requires a complete persisted member set")
        return self._save_unchecked(publication)

    @transaction.atomic
    def _save_unchecked(self, publication: CanonicalPublication) -> CanonicalPublication:
        """Persist a candidate or a publication after caller-side checks."""

        model, _ = CanonicalPublicationModel._default_manager.update_or_create(
            publication_id=_uuid(publication.publication_id),
            defaults={
                "dataset_key": publication.dataset_key,
                "publication_key": publication.publication_key,
                "policy_version": publication.policy_version,
                "state": publication.state.value,
                "selected_source": publication.selected_source,
                "publication_hash": publication.publication_hash,
                "member_count": publication.member_count,
                "conflict_count": publication.conflict_count,
                "coverage_requested_count": publication.coverage.requested_count,
                "coverage_eligible_count": publication.coverage.eligible_count,
                "coverage_selected_count": publication.coverage.selected_count,
                "coverage_missing_count": publication.coverage.missing_count,
                "coverage_conflict_count": publication.coverage.conflict_count,
                "as_of": publication.as_of,
                "published_at": publication.published_at,
                "superseded_at": publication.superseded_at,
                "must_not_use_for_decision": publication.must_not_use_for_decision,
                "blocked_reason": publication.blocked_reason,
                "created_by": publication.created_by,
                "run_id": _uuid(publication.run_id) if publication.run_id else None,
            },
        )
        CoverageSnapshotModel._default_manager.update_or_create(
            publication_id=model.publication_id,
            defaults={
                "coverage_id": _uuid(publication.coverage.coverage_id),
                "requested_count": publication.coverage.requested_count,
                "eligible_count": publication.coverage.eligible_count,
                "selected_count": publication.coverage.selected_count,
                "missing_count": publication.coverage.missing_count,
                "conflict_count": publication.coverage.conflict_count,
                "generated_at": publication.coverage.generated_at,
            },
        )
        return model.to_domain()

    @transaction.atomic
    def publish(self, publication: CanonicalPublication) -> CanonicalPublication:
        """Publish one candidate and supersede the previous scope version."""

        if publication.state is not PublicationState.PUBLISHED:
            raise ValueError("publish() requires a PUBLISHED publication")
        now = publication.published_at
        if now is None:
            raise ValueError("Published publication requires published_at")
        if publication.as_of is None:
            raise ValueError("Published publication requires an explicit as_of boundary")
        if publication.as_of > now:
            raise ValueError("Publication as_of cannot be later than published_at")
        self._ensure_publish_time_is_monotonic(publication)
        if publication.coverage.publication_id != publication.publication_id:
            raise ValueError("Publication coverage must reference the same publication")
        if publication.coverage.selected_count != publication.member_count:
            raise ValueError("Publication member_count must match selected coverage count")
        persisted_count = PublicationMemberModel._default_manager.filter(
            publication_id=_uuid(publication.publication_id)
        ).count()
        if persisted_count != publication.member_count:
            raise ValueError("Published publication requires a complete persisted member set")
        persisted_members = list(
            PublicationMemberModel._default_manager.filter(
                publication_id=_uuid(publication.publication_id)
            ).values("member_id", "fact_table", "fact_pk", "observed_at")
        )
        if any(
            row["observed_at"] is None or row["observed_at"] > publication.as_of
            for row in persisted_members
        ):
            raise ValueError("Published publication members exceed publication as_of")
        if len({row["member_id"] for row in persisted_members}) != persisted_count:
            raise ValueError("Published publication members must have unique member_id values")
        if (
            len({(row["fact_table"], row["fact_pk"]) for row in persisted_members})
            != persisted_count
        ):
            raise ValueError("Published publication members must reference unique canonical facts")
        CanonicalPublicationModel._default_manager.filter(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            state=PublicationState.PUBLISHED.value,
        ).exclude(publication_id=_uuid(publication.publication_id)).update(
            state=PublicationState.SUPERSEDED.value,
            superseded_at=now,
        )
        return self._save_unchecked(publication)

    @transaction.atomic
    def publish_with_members(
        self,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> CanonicalPublication:
        """Atomically stage, attach, verify and publish one member snapshot.

        Facts are never exposed through the published state while members are
        being written.  Any member mismatch or persistence failure rolls back
        both the candidate and its member rows, leaving the previous
        publication untouched.
        """

        self._validate_publish_batch(publication, members)
        self._ensure_publish_time_is_monotonic(publication)
        publication_id = _uuid(publication.publication_id)
        expected_keys = {member.natural_key for member in members}
        existing_keys = set(
            PublicationMemberModel._default_manager.filter(
                publication_id=publication_id
            ).values_list("natural_key", flat=True)
        )
        if existing_keys and existing_keys != expected_keys:
            raise ValueError("Existing publication members do not match requested snapshot")

        # Keep the row invisible to current readers until all members are
        # present and verified.  ``published_at``/``as_of`` remain attached to
        # the candidate for auditability but its state is not current.
        self._save_unchecked(replace(publication, state=PublicationState.CANDIDATE))
        for member in members:
            self.add_member(member)

        persisted_members = PublicationMemberModel._default_manager.filter(
            publication_id=publication_id
        )
        persisted_keys = set(persisted_members.values_list("natural_key", flat=True))
        persisted_count = persisted_members.count()
        if persisted_count != publication.member_count or persisted_keys != expected_keys:
            raise ValueError("Persisted publication member snapshot is incomplete")

        now = publication.published_at
        if now is None:
            raise ValueError("Published publication requires published_at")
        CanonicalPublicationModel._default_manager.filter(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            state=PublicationState.PUBLISHED.value,
        ).exclude(publication_id=publication_id).update(
            state=PublicationState.SUPERSEDED.value,
            superseded_at=now,
        )
        return self._save_unchecked(publication)

    @staticmethod
    def _validate_publish_batch(
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
    ) -> None:
        """Defend the atomic writer when called outside its Application port."""

        if publication.state is not PublicationState.PUBLISHED:
            raise ValueError("publish_with_members() requires a PUBLISHED publication")
        if publication.as_of is None:
            raise ValueError("Published publication requires an explicit as_of boundary")
        if publication.published_at is None:
            raise ValueError("Published publication requires published_at")
        if publication.as_of > publication.published_at:
            raise ValueError("Publication as_of cannot be later than published_at")
        if publication.coverage.publication_id != publication.publication_id:
            raise ValueError("Publication coverage must reference the same publication")
        if publication.coverage.selected_count != publication.member_count:
            raise ValueError("Publication member_count must match selected coverage count")
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

    @staticmethod
    def _ensure_publish_time_is_monotonic(publication: CanonicalPublication) -> None:
        """Reject a late publication that would rewind the current scope.

        ``get_as_of`` relies on published/superseded timestamps forming valid
        intervals.  Superseding an already-current row with an earlier (or
        equal) ``published_at`` would make its interval end before it starts
        and could expose an out-of-order snapshot as current.  Keep this
        invariant at the repository boundary for both publication entry
        points.
        """

        published_at = publication.published_at
        if published_at is None:
            raise ValueError("Published publication requires published_at")

        active = CanonicalPublicationModel._default_manager.filter(
            dataset_key=publication.dataset_key,
            publication_key=publication.publication_key,
            state=PublicationState.PUBLISHED.value,
        ).exclude(publication_id=_uuid(publication.publication_id))
        if active.filter(published_at__isnull=True).exists():
            raise ValueError("Cannot publish while current publication has no published_at")
        latest = active.order_by("-published_at").first()
        if (
            latest is not None
            and latest.published_at is not None
            and published_at <= latest.published_at
        ):
            raise ValueError("Publication published_at must be later than current publication")

    def get_current(self, dataset_key: str, publication_key: str) -> CanonicalPublication | None:
        """Return only the active published publication for a scope."""

        model = (
            CanonicalPublicationModel._default_manager.filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
                state=PublicationState.PUBLISHED.value,
                must_not_use_for_decision=False,
            )
            .order_by("-published_at")
            .first()
        )
        return model.to_domain() if model is not None else None

    def get_as_of(
        self,
        dataset_key: str,
        publication_key: str,
        as_of: datetime,
    ) -> CanonicalPublication | None:
        """Return the latest publication visible at an historical boundary."""

        model = (
            CanonicalPublicationModel._default_manager.filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
                state__in=[PublicationState.PUBLISHED.value, PublicationState.SUPERSEDED.value],
                published_at__lte=as_of,
            )
            .filter(
                # A superseded version is valid until its supersede time; a
                # current version remains valid after publication.
                superseded_at__isnull=True,
            )
            .order_by("-published_at")
            .first()
        )
        if model is None:
            model = (
                CanonicalPublicationModel._default_manager.filter(
                    dataset_key=dataset_key,
                    publication_key=publication_key,
                    state=PublicationState.SUPERSEDED.value,
                    published_at__lte=as_of,
                    superseded_at__gt=as_of,
                )
                .order_by("-published_at")
                .first()
            )
        return model.to_domain() if model is not None else None

    def add_member(self, member: PublicationMember) -> PublicationMember:
        """Add one selected fact reference idempotently."""

        model, _ = PublicationMemberModel._default_manager.update_or_create(
            publication_id=_uuid(member.publication_id),
            natural_key=member.natural_key,
            defaults={
                "member_id": _uuid(member.member_id),
                "dataset_key": member.dataset_key,
                "source": member.source,
                "source_record_id": member.source_record_id,
                "fact_table": member.fact_table,
                "fact_pk": member.fact_pk,
                "observed_at": member.observed_at,
                "raw_payload_hash": member.raw_payload_hash,
                "quality_status": member.quality_status,
                "revision_number": member.revision_number,
            },
        )
        return model.to_domain()

    def list_members(self, publication_id: str) -> list[PublicationMember]:
        """Return selected members in deterministic natural-key order."""

        return [
            model.to_domain()
            for model in PublicationMemberModel._default_manager.filter(
                publication_id=_uuid(publication_id)
            ).order_by("natural_key")
        ]

    def get_oldest_member_observed_at(self, publication_id: str) -> datetime | None:
        """Return the oldest source observation represented by a publication."""

        value = (
            PublicationMemberModel._default_manager.filter(
                publication_id=_uuid(publication_id),
                observed_at__isnull=False,
            )
            .order_by("observed_at")
            .values_list("observed_at", flat=True)
            .first()
        )
        return value


__all__ = [
    "CanonicalPublicationRepository",
    "QuarantineRepository",
    "SyncBatchRepository",
    "SyncCheckpointRepository",
    "SyncRunRepository",
]
