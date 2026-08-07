"""Trusted archive export, verification and isolated-restore use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.application.retention import RetentionPolicyRepositoryPort
from apps.data_center.domain.contracts import DatasetContract
from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.domain.retention import (
    ArchiveArtifact,
    ArchiveManifest,
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
    ArchiveState,
)


class DatasetContractReadPort(Protocol):
    """Read active dataset contract metadata for archive lineage."""

    def get_active(self, dataset_key: str) -> DatasetContract | None: ...


class ArchiveCandidateReadPort(Protocol):
    """Read bounded RawPayload rows not already registered in an archive."""

    def list_unarchived(
        self,
        dataset_key: str,
        *,
        before: datetime,
        now: datetime,
        limit: int,
    ) -> list[RawPayload]: ...


class ArchiveManifestWritePort(Protocol):
    """Persist immutable archive coverage and restore evidence."""

    def save_export(
        self,
        manifest: ArchiveManifest,
        members: tuple[ArchiveMember, ...],
    ) -> ArchiveManifest: ...

    def get(self, archive_id: str) -> ArchiveManifest | None: ...

    def list_members(self, archive_id: str) -> tuple[ArchiveMember, ...]: ...

    def mark_verified(
        self,
        archive_id: str,
        *,
        verified_at: datetime | None = None,
    ) -> ArchiveManifest: ...

    def record_restore(self, audit: ArchiveRestoreAudit) -> ArchiveManifest: ...

    def get_restore_audit(self, operation_key: str) -> ArchiveRestoreAudit | None: ...


class RawArchiveStorePort(Protocol):
    """External byte-store port used only by Infrastructure adapters."""

    def write(
        self,
        *,
        archive_id: str,
        dataset_key: str,
        contract_version: str,
        schema_version: str,
        payloads: tuple[RawPayload, ...],
        created_at: datetime,
    ) -> ArchiveArtifact: ...

    def inspect(self, location: str) -> ArchiveArtifact: ...

    def restore_to_staging(self, location: str) -> ArchiveArtifact: ...


class ArchiveCapacityPort(Protocol):
    """Fail-closed projected capacity gate for cold archive I/O."""

    def can_write(self, projected_bytes: int) -> bool: ...


@dataclass(frozen=True)
class ArchiveOperationResult:
    """Stable business outcome for archive lifecycle tasks."""

    outcome: str
    operation: str
    archive_id: str = ""
    dataset_key: str = ""
    requested: int = 1
    candidates: int = 0
    succeeded: int = 0
    failed: int = 0
    stored: int = 0
    object_count: int = 0
    size_bytes: int = 0
    reason: str = ""
    verified_at: datetime | None = None
    restored_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the normalized Celery business-result payload."""

        return {
            "outcome": self.outcome,
            "success": self.outcome in {"success", "noop"},
            "operation": self.operation,
            "archive_id": self.archive_id,
            "dataset_key": self.dataset_key,
            "requested": self.requested,
            "candidates": self.candidates,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "stored": self.stored,
            "object_count": self.object_count,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "restored_at": self.restored_at.isoformat() if self.restored_at else None,
        }


class ArchiveRawPayloadsUseCase:
    """Export one bounded expired RawPayload batch into immutable cold bytes."""

    def __init__(
        self,
        policies: RetentionPolicyRepositoryPort,
        contracts: DatasetContractReadPort,
        candidates: ArchiveCandidateReadPort,
        manifests: ArchiveManifestWritePort,
        store: RawArchiveStorePort,
        capacity: ArchiveCapacityPort,
    ) -> None:
        self._policies = policies
        self._contracts = contracts
        self._candidates = candidates
        self._manifests = manifests
        self._store = store
        self._capacity = capacity

    def execute(
        self,
        *,
        dataset_key: str,
        limit: int = 100,
        now: datetime | None = None,
    ) -> ArchiveOperationResult:
        """Write and register an immutable archive without deleting source rows."""

        if not dataset_key.strip():
            raise ValueError("dataset_key is required")
        if isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        policy = self._policies.get_active(dataset_key)
        if policy is None:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="export",
                dataset_key=dataset_key,
                requested=limit,
                reason="retention_policy_missing_or_inactive",
            )
        contract = self._contracts.get_active(dataset_key)
        if contract is None:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="export",
                dataset_key=dataset_key,
                requested=limit,
                reason="dataset_contract_missing_or_inactive",
            )
        if policy.archive_retention_days is None:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="export",
                dataset_key=dataset_key,
                requested=limit,
                reason="archive_retention_days_missing",
            )
        archive_after_days = policy.archive_after_days or policy.retention_days
        cutoff = moment - timedelta(days=archive_after_days)
        rows = tuple(
            self._candidates.list_unarchived(
                dataset_key,
                before=cutoff,
                now=moment,
                limit=limit,
            )
        )
        if not rows:
            return ArchiveOperationResult(
                outcome="noop",
                operation="export",
                dataset_key=dataset_key,
                requested=limit,
                reason="no_expired_raw_payloads",
            )
        projected_bytes = max(
            1,
            sum(max(1, row.payload_size_bytes) for row in rows) + 1024 * 1024,
        )
        if not self._capacity.can_write(projected_bytes):
            return ArchiveOperationResult(
                outcome="blocked",
                operation="export",
                dataset_key=dataset_key,
                requested=limit,
                candidates=len(rows),
                reason="archive_projected_storage_pressure_blocked",
            )
        material = "|".join(
            (
                dataset_key,
                contract.key.contract_version,
                contract.key.schema_version,
                *(f"{row.payload_id}:{row.payload_hash}" for row in rows),
            )
        )
        archive_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:raw-archive:{material}"))
        artifact = self._store.write(
            archive_id=archive_id,
            dataset_key=dataset_key,
            contract_version=contract.key.contract_version,
            schema_version=contract.key.schema_version,
            payloads=rows,
            created_at=moment,
        )
        expected_members = tuple(
            ArchiveMember(
                payload_id=row.payload_id,
                payload_hash=row.payload_hash,
                record_digest=raw_payload_record_digest(row),
                schema_fingerprint=row.schema_fingerprint,
                fetched_at=row.fetched_at,
                size_bytes=row.payload_size_bytes,
            )
            for row in rows
        )
        if (
            artifact.archive_id != archive_id
            or artifact.dataset_key != dataset_key
            or artifact.contract_version != contract.key.contract_version
            or artifact.schema_version != contract.key.schema_version
            or artifact.members != expected_members
        ):
            raise ValueError("archive_store_evidence_mismatch")
        manifest = ArchiveManifest(
            archive_id=artifact.archive_id,
            dataset_key=artifact.dataset_key,
            object_count=artifact.object_count,
            size_bytes=artifact.size_bytes,
            location=artifact.location,
            checksum=artifact.checksum,
            state=ArchiveState.EXPORTED,
            created_at=artifact.created_at,
            contract_version=artifact.contract_version,
            schema_version=artifact.schema_version,
            format_version=artifact.format_version,
            encryption_algorithm=artifact.encryption_algorithm,
            encryption_key_ref=artifact.encryption_key_ref,
            encryption_key_version=artifact.encryption_key_version,
            coverage_started_at=artifact.coverage_started_at,
            coverage_ended_at=artifact.coverage_ended_at,
            retention_until=moment + timedelta(days=policy.archive_retention_days),
        )
        saved = self._manifests.save_export(manifest, artifact.members)
        return ArchiveOperationResult(
            outcome="success",
            operation="export",
            archive_id=saved.archive_id,
            dataset_key=saved.dataset_key,
            requested=limit,
            candidates=len(rows),
            succeeded=len(rows),
            stored=len(rows),
            object_count=saved.object_count,
            size_bytes=saved.size_bytes,
            reason="archive_exported",
        )


class VerifyStoredArchiveUseCase:
    """Independently read cold bytes before promoting a manifest to verified."""

    def __init__(self, manifests: ArchiveManifestWritePort, store: RawArchiveStorePort) -> None:
        self._manifests = manifests
        self._store = store

    def execute(
        self,
        *,
        archive_id: str,
        now: datetime | None = None,
    ) -> ArchiveOperationResult:
        """Read the configured store; caller-supplied checksums are never accepted."""

        if not archive_id.strip():
            raise ValueError("archive_id is required")
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        manifest = self._manifests.get(archive_id)
        if manifest is None:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="verify",
                archive_id=archive_id,
                reason="archive_manifest_missing",
            )
        if manifest.state not in {ArchiveState.EXPORTED, ArchiveState.VERIFIED}:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="verify",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                reason="archive_manifest_state_not_verifiable",
            )
        artifact = self._store.inspect(manifest.location)
        members = self._manifests.list_members(archive_id)
        if not artifact.matches_manifest(manifest, members):
            return ArchiveOperationResult(
                outcome="blocked",
                operation="verify",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                object_count=artifact.object_count,
                size_bytes=artifact.size_bytes,
                reason="archive_manifest_evidence_mismatch",
            )
        if manifest.state is ArchiveState.VERIFIED:
            return ArchiveOperationResult(
                outcome="noop",
                operation="verify",
                archive_id=manifest.archive_id,
                dataset_key=manifest.dataset_key,
                succeeded=1,
                stored=1,
                object_count=manifest.object_count,
                size_bytes=manifest.size_bytes,
                reason="archive_manifest_already_verified",
                verified_at=manifest.verified_at,
            )
        verified = self._manifests.mark_verified(archive_id, verified_at=moment)
        return ArchiveOperationResult(
            outcome="success",
            operation="verify",
            archive_id=verified.archive_id,
            dataset_key=verified.dataset_key,
            succeeded=1,
            stored=1,
            object_count=verified.object_count,
            size_bytes=verified.size_bytes,
            reason="archive_manifest_verified_from_store",
            verified_at=verified.verified_at,
        )


class AuditArchiveRestoreUseCase:
    """Restore verified bytes into an isolated staging area and record evidence."""

    def __init__(self, manifests: ArchiveManifestWritePort, store: RawArchiveStorePort) -> None:
        self._manifests = manifests
        self._store = store

    def execute(
        self,
        *,
        archive_id: str,
        operation_id: str,
        now: datetime | None = None,
    ) -> ArchiveOperationResult:
        """Perform a real staging restore; database state is not used as byte proof."""

        if not archive_id.strip():
            raise ValueError("archive_id is required")
        if not operation_id.strip():
            raise ValueError("operation_id is required")
        started_at = now or datetime.now(UTC)
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        manifest = self._manifests.get(archive_id)
        if manifest is None:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="restore",
                archive_id=archive_id,
                reason="archive_manifest_missing",
            )
        if manifest.state is not ArchiveState.VERIFIED:
            return ArchiveOperationResult(
                outcome="blocked",
                operation="restore",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                reason="archive_manifest_not_verified",
            )
        operation_key = f"archive-restore:{archive_id}:{operation_id.strip()}"
        audit_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:{operation_key}"))
        existing_audit = self._manifests.get_restore_audit(operation_key)
        if existing_audit is not None:
            return ArchiveOperationResult(
                outcome=(
                    "noop" if existing_audit.outcome is ArchiveRestoreOutcome.SUCCESS else "failed"
                ),
                operation="restore",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                succeeded=(1 if existing_audit.outcome is ArchiveRestoreOutcome.SUCCESS else 0),
                failed=(1 if existing_audit.outcome is ArchiveRestoreOutcome.FAILED else 0),
                object_count=existing_audit.observed_object_count,
                size_bytes=existing_audit.observed_size_bytes,
                reason="archive_restore_operation_already_recorded",
                restored_at=existing_audit.finished_at,
            )
        members = self._manifests.list_members(archive_id)
        try:
            artifact = self._store.restore_to_staging(manifest.location)
        except Exception as exc:
            finished_at = datetime.now(UTC)
            self._manifests.record_restore(
                ArchiveRestoreAudit(
                    audit_id=audit_id,
                    operation_key=operation_key,
                    archive_id=archive_id,
                    outcome=ArchiveRestoreOutcome.FAILED,
                    observed_checksum="",
                    observed_object_count=0,
                    observed_size_bytes=0,
                    restored_object_count=0,
                    restored_bytes=0,
                    started_at=started_at,
                    finished_at=finished_at,
                    reason=f"archive_restore_failed:{exc.__class__.__name__}",
                )
            )
            return ArchiveOperationResult(
                outcome="failed",
                operation="restore",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                failed=1,
                reason="archive_restore_failed",
            )
        finished_at = datetime.now(UTC)
        matches = artifact.matches_manifest(manifest, members)
        outcome = ArchiveRestoreOutcome.SUCCESS if matches else ArchiveRestoreOutcome.FAILED
        audit = ArchiveRestoreAudit(
            audit_id=audit_id,
            operation_key=operation_key,
            archive_id=archive_id,
            outcome=outcome,
            observed_checksum=artifact.checksum,
            observed_object_count=artifact.object_count,
            observed_size_bytes=artifact.size_bytes,
            restored_object_count=artifact.object_count,
            restored_bytes=artifact.size_bytes,
            started_at=started_at,
            finished_at=finished_at,
            reason="archive_staging_restore_verified" if matches else "archive_restore_mismatch",
        )
        updated = self._manifests.record_restore(audit)
        if not matches:
            return ArchiveOperationResult(
                outcome="failed",
                operation="restore",
                archive_id=archive_id,
                dataset_key=manifest.dataset_key,
                failed=1,
                object_count=artifact.object_count,
                size_bytes=artifact.size_bytes,
                reason="archive_restore_mismatch",
            )
        return ArchiveOperationResult(
            outcome="success",
            operation="restore",
            archive_id=archive_id,
            dataset_key=manifest.dataset_key,
            succeeded=1,
            stored=1,
            object_count=artifact.object_count,
            size_bytes=artifact.size_bytes,
            reason="archive_staging_restore_verified",
            verified_at=updated.verified_at,
            restored_at=updated.last_restored_at,
        )


__all__ = [
    "ArchiveCapacityPort",
    "ArchiveCandidateReadPort",
    "ArchiveManifestWritePort",
    "ArchiveOperationResult",
    "ArchiveRawPayloadsUseCase",
    "AuditArchiveRestoreUseCase",
    "DatasetContractReadPort",
    "RawArchiveStorePort",
    "VerifyStoredArchiveUseCase",
]
