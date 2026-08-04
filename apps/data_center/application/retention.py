"""Application ports for retention, holds and verified archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
)


class RetentionPolicyRepositoryPort(Protocol):
    """Persistence port for retention policies."""

    def save(self, policy: RetentionPolicy) -> RetentionPolicy: ...

    def activate(self, policy: RetentionPolicy) -> RetentionPolicy: ...

    def get_active(self, dataset_key: str) -> RetentionPolicy | None: ...


class StorageHoldRepositoryPort(Protocol):
    """Persistence port for deletion holds."""

    def save(self, hold: StorageHold) -> StorageHold: ...

    def has_active_hold(
        self, resource_type: str, resource_key: str, *, now: datetime | None = None
    ) -> bool: ...


class ArchiveManifestRepositoryPort(Protocol):
    """Persistence port for archive evidence."""

    def save(self, manifest: ArchiveManifest) -> ArchiveManifest: ...

    def get(self, archive_id: str) -> ArchiveManifest | None: ...

    def mark_verified(
        self, archive_id: str, *, verified_at: datetime | None = None
    ) -> ArchiveManifest: ...

    def has_verified_for_dataset(
        self, dataset_key: str, *, now: datetime | None = None
    ) -> bool: ...


class RetentionCandidateRepositoryPort(Protocol):
    """Bounded raw-payload candidate and deletion port."""

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]: ...

    def delete(self, payload_id: str) -> int: ...


class RetentionRunRepositoryPort(Protocol):
    """Persistence port for append-only retention run evidence."""

    def save(self, run: RetentionRun) -> RetentionRun: ...


@dataclass(frozen=True)
class RetentionCleanupResult:
    """Auditable outcome of one bounded retention pass."""

    outcome: str
    dataset_key: str
    requested: int
    candidates: int
    planned: int
    deleted: int
    held: int
    blocked: int
    cutoff: datetime | None
    reason: str = ""
    policy_version: int | None = None
    bytes_planned: int = 0
    bytes_deleted: int = 0

    def to_dict(self) -> dict[str, object]:
        """Return a stable task payload."""

        return {
            "outcome": self.outcome,
            "success": self.outcome in {"success", "noop"},
            "dataset_key": self.dataset_key,
            "requested": self.requested,
            "candidates": self.candidates,
            "planned": self.planned,
            "deleted": self.deleted,
            "held": self.held,
            "blocked": self.blocked,
            "cutoff": self.cutoff.isoformat() if self.cutoff is not None else None,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "bytes_planned": self.bytes_planned,
            "bytes_deleted": self.bytes_deleted,
        }


@dataclass(frozen=True)
class ArchiveVerificationResult:
    """Auditable result of comparing one archive manifest with its artifact."""

    outcome: str
    archive_id: str
    object_count: int
    size_bytes: int
    reason: str = ""
    verified_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return the stable task contract payload."""

        return {
            "outcome": self.outcome,
            "success": self.outcome in {"success", "noop"},
            "archive_id": self.archive_id,
            "requested": 1,
            "succeeded": 1 if self.outcome in {"success", "noop"} else 0,
            "failed": 1 if self.outcome == "failed" else 0,
            "blocked": 1 if self.outcome == "blocked" else 0,
            "object_count": self.object_count,
            "size_bytes": self.size_bytes,
            "reason": self.reason,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }


class VerifyArchiveManifestUseCase:
    """Verify immutable archive evidence before it can gate raw deletion."""

    def __init__(self, manifests: ArchiveManifestRepositoryPort) -> None:
        self._manifests = manifests

    def execute(
        self,
        *,
        archive_id: str,
        observed_checksum: str,
        observed_object_count: int,
        observed_size_bytes: int,
        verified_at: datetime | None = None,
    ) -> ArchiveVerificationResult:
        """Compare caller-supplied artifact evidence and mark it verified.

        The use case intentionally accepts only explicit artifact evidence.  It
        never treats a non-empty manifest checksum as proof that the external
        object was read, and it never changes state when any evidence differs.
        """

        if not isinstance(archive_id, str) or not archive_id.strip():
            raise ValueError("archive_id is required")
        if not isinstance(observed_checksum, str) or not observed_checksum.strip():
            raise ValueError("observed_checksum is required")
        if (
            isinstance(observed_object_count, bool)
            or not isinstance(observed_object_count, int)
            or observed_object_count < 0
        ):
            raise ValueError("observed_object_count must be a non-negative integer")
        if (
            isinstance(observed_size_bytes, bool)
            or not isinstance(observed_size_bytes, int)
            or observed_size_bytes < 0
        ):
            raise ValueError("observed_size_bytes must be a non-negative integer")
        moment = verified_at or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("verified_at must be timezone-aware")

        manifest = self._manifests.get(archive_id.strip())
        if manifest is None:
            return ArchiveVerificationResult(
                outcome="blocked",
                archive_id=archive_id.strip(),
                object_count=observed_object_count,
                size_bytes=observed_size_bytes,
                reason="archive_manifest_missing",
            )
        if manifest.state in {ArchiveState.FAILED, ArchiveState.DELETED}:
            return ArchiveVerificationResult(
                outcome="blocked",
                archive_id=manifest.archive_id,
                object_count=observed_object_count,
                size_bytes=observed_size_bytes,
                reason="archive_manifest_state_not_verifiable",
            )
        if (
            observed_checksum.strip() != manifest.checksum
            or observed_object_count != manifest.object_count
            or observed_size_bytes != manifest.size_bytes
        ):
            return ArchiveVerificationResult(
                outcome="blocked",
                archive_id=manifest.archive_id,
                object_count=observed_object_count,
                size_bytes=observed_size_bytes,
                reason="archive_manifest_evidence_mismatch",
            )
        verified = self._manifests.mark_verified(archive_id, verified_at=moment)
        return ArchiveVerificationResult(
            outcome="success",
            archive_id=verified.archive_id,
            object_count=verified.object_count,
            size_bytes=verified.size_bytes,
            reason="archive_manifest_verified",
            verified_at=verified.verified_at,
        )


class RetentionGuard:
    """Decide whether a resource may be deleted under active policy/holds."""

    def __init__(self, holds: StorageHoldRepositoryPort) -> None:
        self._holds = holds

    def can_delete(
        self, resource_type: str, resource_key: str, *, now: datetime | None = None
    ) -> bool:
        """Return false whenever an unexpired hold exists."""

        return not self._holds.has_active_hold(resource_type, resource_key, now=now)


class RetentionCleanupUseCase:
    """Plan or execute bounded raw cleanup behind policy, archive and hold gates."""

    def __init__(
        self,
        policies: RetentionPolicyRepositoryPort,
        holds: StorageHoldRepositoryPort,
        archives: ArchiveManifestRepositoryPort,
        candidates: RetentionCandidateRepositoryPort,
        runs: RetentionRunRepositoryPort | None = None,
    ) -> None:
        self._policies = policies
        self._guard = RetentionGuard(holds)
        self._archives = archives
        self._candidates = candidates
        self._runs = runs

    def _record_run(
        self,
        result: RetentionCleanupResult,
        *,
        dry_run: bool,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        """Persist one immutable run evidence row when a run repository is configured."""

        if self._runs is None:
            return
        self._runs.save(
            RetentionRun(
                run_id=str(uuid4()),
                dataset_key=result.dataset_key,
                policy_version=result.policy_version,
                dry_run=dry_run,
                outcome=result.outcome,
                requested=result.requested,
                candidates=result.candidates,
                planned=result.planned,
                deleted=result.deleted,
                held=result.held,
                blocked=result.blocked,
                bytes_planned=result.bytes_planned,
                bytes_deleted=result.bytes_deleted,
                cutoff=result.cutoff,
                started_at=started_at,
                finished_at=finished_at,
                reason=result.reason,
            )
        )

    def execute(
        self,
        *,
        dataset_key: str,
        limit: int = 100,
        now: datetime | None = None,
        dry_run: bool = True,
    ) -> RetentionCleanupResult:
        """Run one bounded pass; deletion is impossible without verified archive evidence."""

        if not dataset_key.strip():
            raise ValueError("dataset_key is required")
        if isinstance(limit, bool) or limit < 1 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        policy = self._policies.get_active(dataset_key)
        if policy is None:
            result = RetentionCleanupResult(
                outcome="blocked",
                dataset_key=dataset_key,
                requested=limit,
                candidates=0,
                planned=0,
                deleted=0,
                held=0,
                blocked=0,
                cutoff=None,
                reason="retention_policy_missing_or_inactive",
            )
            self._record_run(result, dry_run=dry_run, started_at=moment, finished_at=moment)
            return result
        cutoff = moment - timedelta(days=policy.retention_days)
        rows = self._candidates.list_expired(
            dataset_key,
            before=cutoff,
            limit=limit,
            now=moment,
        )
        if not rows:
            result = RetentionCleanupResult(
                outcome="noop",
                dataset_key=dataset_key,
                requested=limit,
                candidates=0,
                planned=0,
                deleted=0,
                held=0,
                blocked=0,
                cutoff=cutoff,
                reason="no_expired_raw_payloads",
                policy_version=policy.version,
            )
            self._record_run(result, dry_run=dry_run, started_at=moment, finished_at=moment)
            return result
        archive_ready = self._archives.has_verified_for_dataset(dataset_key, now=moment)
        planned = 0
        deleted = 0
        held = 0
        blocked = 0
        bytes_planned = 0
        bytes_deleted = 0
        retention_blocked = 0
        for row in rows:
            payload_size = int(row.payload_size_bytes)
            if not self._guard.can_delete("raw_payload", row.payload_id, now=moment):
                held += 1
                continue
            # The row-level retention deadline is an independent, stricter
            # guard than the dataset policy.  Keep this check in the
            # application layer as a fail-closed defence for legacy/custom
            # candidate repositories that do not filter it themselves.
            if row.retention_until is not None and row.retention_until > moment:
                blocked += 1
                retention_blocked += 1
                continue
            if not archive_ready:
                blocked += 1
                continue
            if dry_run:
                planned += 1
                bytes_planned += payload_size
            else:
                deleted_count = self._candidates.delete(row.payload_id)
                deleted += deleted_count
                if deleted_count > 0:
                    bytes_deleted += payload_size
        if retention_blocked and deleted == 0 and planned == 0 and held == 0:
            outcome = "blocked"
            reason = "retention_until_not_reached"
        elif blocked and deleted == 0 and planned == 0:
            outcome = "blocked"
            reason = "verified_archive_missing"
        elif held or blocked:
            outcome = "partial"
            reason = "some_candidates_held_or_missing_archive"
        elif dry_run:
            outcome = "noop"
            reason = "dry_run_planned_only"
        else:
            outcome = "success"
            reason = "expired_payloads_deleted"
        result = RetentionCleanupResult(
            outcome=outcome,
            dataset_key=dataset_key,
            requested=limit,
            candidates=len(rows),
            planned=planned,
            deleted=deleted,
            held=held,
            blocked=blocked,
            cutoff=cutoff,
            reason=reason,
            policy_version=policy.version,
            bytes_planned=bytes_planned,
            bytes_deleted=bytes_deleted,
        )
        self._record_run(result, dry_run=dry_run, started_at=moment, finished_at=moment)
        return result


__all__ = [
    "ArchiveManifestRepositoryPort",
    "ArchiveVerificationResult",
    "RetentionCandidateRepositoryPort",
    "RetentionCleanupResult",
    "RetentionCleanupUseCase",
    "RetentionGuard",
    "RetentionPolicyRepositoryPort",
    "RetentionRunRepositoryPort",
    "StorageHoldRepositoryPort",
    "VerifyArchiveManifestUseCase",
]
