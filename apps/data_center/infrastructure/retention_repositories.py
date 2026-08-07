"""Repositories for retention policies, holds and archive manifests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q

from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
    ArchiveState,
    RetentionPlan,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
)

from .archive_models import ArchiveMemberModel, ArchiveRestoreAuditModel
from .models import ArchiveManifestModel, RetentionPolicyModel, StorageHoldModel
from .retention_models import RetentionPlanMemberModel, RetentionPlanModel, RetentionRunModel


def _uuid(value: str) -> UUID:
    """Convert domain ID to UUID."""

    return UUID(value)


class RetentionPolicyRepository:
    """Versioned retention policy repository."""

    def save(self, policy: RetentionPolicy) -> RetentionPolicy:
        """Upsert one policy version."""

        model, _ = RetentionPolicyModel._default_manager.update_or_create(
            policy_id=_uuid(policy.policy_id),
            defaults={
                "dataset_key": policy.dataset_key,
                "version": policy.version,
                "retention_days": policy.retention_days,
                "archive_after_days": policy.archive_after_days,
                "archive_retention_days": policy.archive_retention_days,
                "priority": policy.priority,
                "active": policy.active,
            },
        )
        return model.to_domain()

    @transaction.atomic
    def activate(self, policy: RetentionPolicy) -> RetentionPolicy:
        """Activate one policy version and retire others for the dataset."""

        RetentionPolicyModel._default_manager.filter(
            dataset_key=policy.dataset_key, active=True
        ).update(active=False)
        return self.save(replace(policy, active=True))

    def get_active(self, dataset_key: str) -> RetentionPolicy | None:
        """Return the active policy for a dataset."""

        model = (
            RetentionPolicyModel._default_manager.filter(dataset_key=dataset_key, active=True)
            .order_by("-version")
            .first()
        )
        return model.to_domain() if model is not None else None


class RetentionRunRepository:
    """Append-only repository for retention execution evidence."""

    def save(self, run: RetentionRun) -> RetentionRun:
        """Persist one retention run idempotently by its run identifier."""

        defaults = {
            "dataset_key": run.dataset_key,
            "policy_version": run.policy_version,
            "dry_run": run.dry_run,
            "outcome": run.outcome,
            "requested": run.requested,
            "candidates": run.candidates,
            "planned": run.planned,
            "deleted": run.deleted,
            "held": run.held,
            "blocked": run.blocked,
            "bytes_planned": run.bytes_planned,
            "bytes_deleted": run.bytes_deleted,
            "cutoff": run.cutoff,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "reason": run.reason,
        }
        model, created = RetentionRunModel._default_manager.get_or_create(
            run_id=_uuid(run.run_id),
            defaults=defaults,
        )
        if not created and model.to_domain() != run:
            raise ValueError("retention_run_immutable_conflict")
        return model.to_domain()


class RetentionPlanRepository:
    """Create immutable plan snapshots and serialize their enforcement claims."""

    @staticmethod
    def _members(plan_id: str) -> tuple[RetentionPlanMember, ...]:
        return tuple(
            model.to_domain()
            for model in RetentionPlanMemberModel._default_manager.filter(
                plan_id=_uuid(plan_id)
            ).order_by("ordinal")
        )

    def get_by_operation_id(
        self, operation_id: str
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]] | None:
        """Return an idempotent plan snapshot without rescanning source rows."""

        model = RetentionPlanModel._default_manager.filter(operation_id=operation_id).first()
        if model is None:
            return None
        plan = model.to_domain()
        return plan, self._members(plan.plan_id)

    @transaction.atomic
    def create(
        self, plan: RetentionPlan, members: tuple[RetentionPlanMember, ...]
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]]:
        """Create the plan header and exact members in one transaction."""

        defaults = {
            "plan_id": _uuid(plan.plan_id),
            "dataset_key": plan.dataset_key,
            "policy_id": _uuid(plan.policy_id),
            "policy_version": plan.policy_version,
            "requested": plan.requested,
            "candidates": plan.candidates,
            "planned": plan.planned,
            "held": plan.held,
            "blocked": plan.blocked,
            "bytes_planned": plan.bytes_planned,
            "cutoff": plan.cutoff,
            "created_at": plan.created_at,
            "expires_at": plan.expires_at,
            "snapshot_digest": plan.snapshot_digest,
            "status": plan.status.value,
            "outcome": plan.outcome,
            "reason": plan.reason,
        }
        model, created = RetentionPlanModel._default_manager.get_or_create(
            operation_id=plan.operation_id,
            defaults=defaults,
        )
        if not created:
            persisted = model.to_domain()
            if persisted != plan or self._members(persisted.plan_id) != members:
                raise ValueError("retention_plan_operation_immutable_conflict")
            return persisted, members
        RetentionPlanMemberModel._default_manager.bulk_create(
            [
                RetentionPlanMemberModel(
                    plan_id=model.plan_id,
                    ordinal=member.ordinal,
                    payload_id=_uuid(member.payload_id),
                    payload_hash=member.payload_hash,
                    record_digest=member.record_digest,
                    schema_fingerprint=member.schema_fingerprint,
                    fetched_at=member.fetched_at,
                    retention_until=member.retention_until,
                    size_bytes=member.size_bytes,
                    decision=member.decision.value,
                    archive_id=_uuid(member.archive_id) if member.archive_id else None,
                    execution=member.execution.value,
                    execution_reason=member.execution_reason,
                    deleted_at=member.deleted_at,
                )
                for member in members
            ]
        )
        persisted_members = self._members(plan.plan_id)
        if persisted_members != members:
            raise ValueError("retention_plan_member_immutable_conflict")
        return model.to_domain(), persisted_members

    @transaction.atomic
    def claim(
        self,
        plan_id: str,
        *,
        operation_id: str,
        now: datetime,
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...], bool]:
        """Atomically claim one plan; stable retries replay terminal evidence."""

        model = RetentionPlanModel._default_manager.select_for_update().get(plan_id=_uuid(plan_id))
        status = RetentionPlanStatus(model.status)
        if now >= model.expires_at and status is RetentionPlanStatus.READY:
            model.status = RetentionPlanStatus.EXPIRED.value
            model.enforce_operation_id = operation_id
            model.outcome = "blocked"
            model.reason = "retention_plan_expired"
            model.finished_at = now
            model.save(
                update_fields=[
                    "status",
                    "enforce_operation_id",
                    "outcome",
                    "reason",
                    "finished_at",
                ]
            )
            plan = model.to_domain()
            return plan, self._members(plan_id), False
        terminal = {
            RetentionPlanStatus.COMPLETED,
            RetentionPlanStatus.PARTIAL,
            RetentionPlanStatus.FAILED,
            RetentionPlanStatus.EXPIRED,
        }
        if status in terminal:
            if model.enforce_operation_id == operation_id:
                plan = model.to_domain()
                return plan, self._members(plan_id), True
            raise ValueError("retention_plan_already_completed")
        if status is RetentionPlanStatus.BLOCKED and model.enforce_operation_id:
            if model.enforce_operation_id == operation_id:
                plan = model.to_domain()
                return plan, self._members(plan_id), True
            raise ValueError("retention_plan_already_completed")
        if status in {RetentionPlanStatus.EMPTY, RetentionPlanStatus.BLOCKED}:
            plan = model.to_domain()
            return plan, self._members(plan_id), False
        if status is RetentionPlanStatus.ENFORCING:
            if model.enforce_operation_id != operation_id:
                raise ValueError("retention_plan_already_claimed")
        else:
            model.status = RetentionPlanStatus.ENFORCING.value
            model.enforce_operation_id = operation_id
            model.outcome = ""
            model.reason = ""
            model.save(update_fields=["status", "enforce_operation_id", "outcome", "reason"])
        plan = model.to_domain()
        return plan, self._members(plan_id), False

    @transaction.atomic
    def save_member(self, plan_id: str, member: RetentionPlanMember) -> RetentionPlanMember:
        """Advance only execution evidence while preserving snapshot identity."""

        model = RetentionPlanMemberModel._default_manager.select_for_update().get(
            plan_id=_uuid(plan_id), payload_id=_uuid(member.payload_id)
        )
        current = model.to_domain()
        if current.snapshot_fields() != member.snapshot_fields():
            raise ValueError("retention_plan_member_immutable_conflict")
        if current.execution.value not in {"pending", member.execution.value}:
            raise ValueError("retention_plan_member_execution_conflict")
        model.execution = member.execution.value
        model.execution_reason = member.execution_reason
        model.deleted_at = member.deleted_at
        model.save(update_fields=["execution", "execution_reason", "deleted_at"])
        return model.to_domain()

    @transaction.atomic
    def finish(self, plan: RetentionPlan) -> RetentionPlan:
        """Persist the terminal summary for the currently claimed operation."""

        model = RetentionPlanModel._default_manager.select_for_update().get(
            plan_id=_uuid(plan.plan_id)
        )
        current = model.to_domain()
        immutable = (
            "operation_id",
            "dataset_key",
            "policy_id",
            "policy_version",
            "requested",
            "candidates",
            "planned",
            "held",
            "blocked",
            "bytes_planned",
            "cutoff",
            "created_at",
            "expires_at",
            "snapshot_digest",
            "enforce_operation_id",
        )
        if any(getattr(current, field) != getattr(plan, field) for field in immutable):
            raise ValueError("retention_plan_immutable_conflict")
        model.status = plan.status.value
        model.outcome = plan.outcome
        model.deleted = plan.deleted
        model.execution_blocked = plan.execution_blocked
        model.failed = plan.failed
        model.bytes_deleted = plan.bytes_deleted
        model.finished_at = plan.finished_at
        model.reason = plan.reason
        model.save(
            update_fields=[
                "status",
                "outcome",
                "deleted",
                "execution_blocked",
                "failed",
                "bytes_deleted",
                "finished_at",
                "reason",
            ]
        )
        return model.to_domain()


class StorageHoldRepository:
    """Hold repository used by retention jobs before deletion."""

    def save(self, hold: StorageHold) -> StorageHold:
        """Upsert one hold."""

        model, _ = StorageHoldModel._default_manager.update_or_create(
            hold_id=_uuid(hold.hold_id),
            defaults={
                "resource_type": hold.resource_type,
                "resource_key": hold.resource_key,
                "reason": hold.reason,
                "created_by": hold.created_by,
                "created_at": hold.created_at,
                "expires_at": hold.expires_at,
                "released_at": hold.released_at,
            },
        )
        return model.to_domain()

    def has_active_hold(
        self, resource_type: str, resource_key: str, *, now: datetime | None = None
    ) -> bool:
        """Return whether a resource is protected by an unexpired hold."""

        moment = now or datetime.now(UTC)
        return (
            StorageHoldModel._default_manager.filter(
                resource_type=resource_type,
                resource_key=resource_key,
                released_at__isnull=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=moment))
            .exists()
        )


class ArchiveManifestRepository:
    """Verified archive manifest repository."""

    def save(self, manifest: ArchiveManifest) -> ArchiveManifest:
        """Create one immutable manifest or return an identical retry."""

        defaults = {
            "dataset_key": manifest.dataset_key,
            "object_count": manifest.object_count,
            "size_bytes": manifest.size_bytes,
            "location": manifest.location,
            "checksum": manifest.checksum,
            "state": manifest.state.value,
            "created_at": manifest.created_at,
            "verified_at": manifest.verified_at,
            "retention_until": manifest.retention_until,
            "contract_version": manifest.contract_version,
            "schema_version": manifest.schema_version,
            "format_version": manifest.format_version,
            "encryption_algorithm": manifest.encryption_algorithm,
            "encryption_key_ref": manifest.encryption_key_ref,
            "encryption_key_version": manifest.encryption_key_version,
            "coverage_started_at": manifest.coverage_started_at,
            "coverage_ended_at": manifest.coverage_ended_at,
            "restore_outcome": manifest.restore_outcome.value,
            "last_restored_at": manifest.last_restored_at,
        }
        model, created = ArchiveManifestModel._default_manager.get_or_create(
            archive_id=_uuid(manifest.archive_id),
            defaults=defaults,
        )
        if not created:
            immutable_fields = (
                "dataset_key",
                "object_count",
                "size_bytes",
                "location",
                "checksum",
                "created_at",
                "contract_version",
                "schema_version",
                "format_version",
                "encryption_algorithm",
                "encryption_key_ref",
                "encryption_key_version",
                "coverage_started_at",
                "coverage_ended_at",
                "retention_until",
            )
            if any(getattr(model, field) != defaults[field] for field in immutable_fields):
                raise ValueError("archive_manifest_immutable_conflict")
        return model.to_domain()

    @transaction.atomic
    def save_export(
        self,
        manifest: ArchiveManifest,
        members: tuple[ArchiveMember, ...],
    ) -> ArchiveManifest:
        """Persist one exported manifest and its exact member coverage atomically."""

        if manifest.state is not ArchiveState.EXPORTED:
            raise ValueError("archive_manifest_export_state_required")
        if not members or len(members) != manifest.object_count:
            raise ValueError("archive_manifest_member_count_mismatch")
        saved = self.save(manifest)
        archive_uuid = _uuid(saved.archive_id)
        existing = tuple(
            model.to_domain()
            for model in ArchiveMemberModel._default_manager.filter(
                archive_id=archive_uuid
            ).order_by("fetched_at", "payload_id")
        )
        ordered = tuple(sorted(members, key=lambda item: (item.fetched_at, item.payload_id)))
        if existing:
            if existing != ordered:
                raise ValueError("archive_manifest_member_immutable_conflict")
            return saved
        ArchiveMemberModel._default_manager.bulk_create(
            [
                ArchiveMemberModel(
                    archive_id=archive_uuid,
                    payload_id=_uuid(member.payload_id),
                    payload_hash=member.payload_hash,
                    record_digest=member.record_digest,
                    schema_fingerprint=member.schema_fingerprint,
                    fetched_at=member.fetched_at,
                    size_bytes=member.size_bytes,
                )
                for member in ordered
            ],
            ignore_conflicts=True,
        )
        persisted = self.list_members(saved.archive_id)
        if persisted != ordered:
            raise ValueError("archive_manifest_member_immutable_conflict")
        return saved

    def get(self, archive_id: str) -> ArchiveManifest | None:
        """Return one archive manifest for explicit external verification."""

        model = ArchiveManifestModel._default_manager.filter(archive_id=_uuid(archive_id)).first()
        return model.to_domain() if model is not None else None

    def list_members(self, archive_id: str) -> tuple[ArchiveMember, ...]:
        """Return exact archive coverage in deterministic artifact order."""

        return tuple(
            model.to_domain()
            for model in ArchiveMemberModel._default_manager.filter(
                archive_id=_uuid(archive_id)
            ).order_by("fetched_at", "payload_id")
        )

    def mark_verified(
        self, archive_id: str, *, verified_at: datetime | None = None
    ) -> ArchiveManifest:
        """Mark an export as verified after checking its local manifest state.

        A failed/deleted manifest cannot be promoted by accident, and legacy
        rows with an empty checksum fail closed before any state mutation.
        This validates the manifest evidence only; external object bytes are
        still verified by the archive worker before calling this method.
        """

        moment = verified_at or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("archive_manifest_verified_at_must_be_timezone_aware")
        model = ArchiveManifestModel._default_manager.get(archive_id=_uuid(archive_id))
        if not str(model.checksum).strip():
            raise ValueError("archive_manifest_checksum_missing")
        if model.state not in {
            ArchiveState.EXPORTED.value,
            ArchiveState.VERIFIED.value,
        }:
            raise ValueError("archive_manifest_state_not_verifiable")
        model.state = ArchiveState.VERIFIED.value
        model.verified_at = moment
        model.save(update_fields=["state", "verified_at"])
        return model.to_domain()

    @transaction.atomic
    def record_restore(self, audit: ArchiveRestoreAudit) -> ArchiveManifest:
        """Append restore evidence and make the latest result the deletion gate."""

        archive_uuid = _uuid(audit.archive_id)
        manifest = ArchiveManifestModel._default_manager.select_for_update().get(
            archive_id=archive_uuid
        )
        if manifest.state != ArchiveState.VERIFIED.value:
            raise ValueError("archive_manifest_not_verified")
        if manifest.verified_at is None:
            raise ValueError("archive_manifest_verified_at_missing")
        if audit.finished_at < manifest.verified_at:
            raise ValueError("archive_restore_precedes_verification")
        if audit.outcome is ArchiveRestoreOutcome.SUCCESS and (
            audit.observed_checksum != manifest.checksum
            or audit.observed_object_count != int(manifest.object_count)
            or audit.observed_size_bytes != int(manifest.size_bytes)
        ):
            raise ValueError("archive_restore_evidence_mismatch")
        defaults = {
            "audit_id": _uuid(audit.audit_id),
            "archive_id": archive_uuid,
            "outcome": audit.outcome.value,
            "observed_checksum": audit.observed_checksum,
            "observed_object_count": audit.observed_object_count,
            "observed_size_bytes": audit.observed_size_bytes,
            "restored_object_count": audit.restored_object_count,
            "restored_bytes": audit.restored_bytes,
            "started_at": audit.started_at,
            "finished_at": audit.finished_at,
            "reason": audit.reason,
        }
        model, created = ArchiveRestoreAuditModel._default_manager.get_or_create(
            operation_key=audit.operation_key,
            defaults=defaults,
        )
        if not created and model.to_domain() != audit:
            raise ValueError("archive_restore_operation_immutable_conflict")
        if manifest.last_restored_at is None or audit.finished_at >= manifest.last_restored_at:
            manifest.restore_outcome = audit.outcome.value
            manifest.last_restored_at = audit.finished_at
            manifest.save(update_fields=["restore_outcome", "last_restored_at"])
        return manifest.to_domain()

    def get_restore_audit(self, operation_key: str) -> ArchiveRestoreAudit | None:
        """Return one idempotent restore operation evidence row."""

        model = ArchiveRestoreAuditModel._default_manager.filter(
            operation_key=operation_key
        ).first()
        return model.to_domain() if model is not None else None

    def find_covering_manifests(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
    ) -> tuple[ArchiveManifest, ...]:
        """Return restored manifests claiming exact coverage for one payload."""

        moment = now or datetime.now(UTC)
        rows = (
            ArchiveManifestModel._default_manager.filter(
                dataset_key=payload.dataset_key,
                state=ArchiveState.VERIFIED.value,
                restore_outcome=ArchiveRestoreOutcome.SUCCESS.value,
                verified_at__isnull=False,
                last_restored_at__isnull=False,
                members__payload_id=_uuid(payload.payload_id),
                members__payload_hash=payload.payload_hash,
                members__record_digest=raw_payload_record_digest(payload),
                coverage_started_at__isnull=False,
                coverage_ended_at__isnull=False,
                coverage_started_at__lte=payload.fetched_at,
                coverage_ended_at__gte=payload.fetched_at,
                verified_at__lte=moment,
                last_restored_at__lte=moment,
            )
            .filter(retention_until__isnull=False, retention_until__gt=moment)
            .filter(last_restored_at__gte=F("verified_at"))
            .order_by("-last_restored_at", "-created_at")
            .distinct()
        )
        return tuple(
            row.to_domain()
            for row in rows
            if ArchiveMemberModel._default_manager.filter(archive_id=row.archive_id).count()
            == int(row.object_count)
        )

    def has_verified_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return the database evidence gate; byte recheck belongs to the gateway."""

        return bool(self.find_covering_manifests(payload, now=now))


__all__ = [
    "ArchiveManifestRepository",
    "RetentionPolicyRepository",
    "RetentionPlanRepository",
    "RetentionRunRepository",
    "StorageHoldRepository",
]
