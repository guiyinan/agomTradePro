"""Repositories for retention policies, holds and archive manifests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
)

from .models import ArchiveManifestModel, RetentionPolicyModel, StorageHoldModel
from .retention_models import RetentionRunModel


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

        model, _ = RetentionRunModel._default_manager.update_or_create(
            run_id=_uuid(run.run_id),
            defaults={
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
            },
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
        """Upsert one archive manifest by immutable ID."""

        model, _ = ArchiveManifestModel._default_manager.update_or_create(
            archive_id=_uuid(manifest.archive_id),
            defaults={
                "dataset_key": manifest.dataset_key,
                "object_count": manifest.object_count,
                "size_bytes": manifest.size_bytes,
                "location": manifest.location,
                "checksum": manifest.checksum,
                "state": manifest.state.value,
                "created_at": manifest.created_at,
                "verified_at": manifest.verified_at,
                "retention_until": manifest.retention_until,
            },
        )
        return model.to_domain()

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
            ArchiveState.PLANNED.value,
            ArchiveState.EXPORTED.value,
            ArchiveState.VERIFIED.value,
        }:
            raise ValueError("archive_manifest_state_not_verifiable")
        model.state = ArchiveState.VERIFIED.value
        model.verified_at = moment
        model.save(update_fields=["state", "verified_at"])
        return model.to_domain()

    def has_verified_for_dataset(self, dataset_key: str, *, now: datetime | None = None) -> bool:
        """Return whether a currently retained verified archive covers a dataset."""

        moment = now or datetime.now(UTC)
        return (
            ArchiveManifestModel._default_manager.filter(
                dataset_key=dataset_key,
                state=ArchiveState.VERIFIED.value,
                verified_at__isnull=False,
            )
            .filter(Q(retention_until__isnull=True) | Q(retention_until__gt=moment))
            .exists()
        )


__all__ = [
    "ArchiveManifestRepository",
    "RetentionPolicyRepository",
    "RetentionRunRepository",
    "StorageHoldRepository",
]
