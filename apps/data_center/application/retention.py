"""Application ports for retention, holds and verified archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import ArchiveManifest, RetentionPolicy, StorageHold


class RetentionPolicyRepositoryPort(Protocol):
    """Persistence port for retention policies."""

    def save(self, policy: RetentionPolicy) -> RetentionPolicy: ...

    def activate(self, policy: RetentionPolicy) -> RetentionPolicy: ...

    def get_active(self, dataset_key: str) -> RetentionPolicy | None: ...


class StorageHoldRepositoryPort(Protocol):
    """Persistence port for deletion holds."""

    def save(self, hold: StorageHold) -> StorageHold: ...

    def has_active_hold(self, resource_type: str, resource_key: str, *, now: datetime | None = None) -> bool: ...


class ArchiveManifestRepositoryPort(Protocol):
    """Persistence port for archive evidence."""

    def save(self, manifest: ArchiveManifest) -> ArchiveManifest: ...

    def mark_verified(self, archive_id: str, *, verified_at: datetime | None = None) -> ArchiveManifest: ...

    def has_verified_for_dataset(self, dataset_key: str, *, now: datetime | None = None) -> bool: ...


class RetentionCandidateRepositoryPort(Protocol):
    """Bounded raw-payload candidate and deletion port."""

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
    ) -> list[RawPayload]: ...

    def delete(self, payload_id: str) -> int: ...


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
        }


class RetentionGuard:
    """Decide whether a resource may be deleted under active policy/holds."""

    def __init__(self, holds: StorageHoldRepositoryPort) -> None:
        self._holds = holds

    def can_delete(self, resource_type: str, resource_key: str, *, now: datetime | None = None) -> bool:
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
    ) -> None:
        self._policies = policies
        self._guard = RetentionGuard(holds)
        self._archives = archives
        self._candidates = candidates

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
            return RetentionCleanupResult(
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
        cutoff = moment - timedelta(days=policy.retention_days)
        rows = self._candidates.list_expired(dataset_key, before=cutoff, limit=limit)
        if not rows:
            return RetentionCleanupResult(
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
            )
        archive_ready = self._archives.has_verified_for_dataset(dataset_key, now=moment)
        planned = 0
        deleted = 0
        held = 0
        blocked = 0
        for row in rows:
            if not self._guard.can_delete("raw_payload", row.payload_id, now=moment):
                held += 1
                continue
            if not archive_ready:
                blocked += 1
                continue
            if dry_run:
                planned += 1
            else:
                deleted += self._candidates.delete(row.payload_id)
        if blocked and deleted == 0 and planned == 0:
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
        return RetentionCleanupResult(
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
        )


__all__ = [
    "ArchiveManifestRepositoryPort",
    "RetentionCandidateRepositoryPort",
    "RetentionCleanupResult",
    "RetentionCleanupUseCase",
    "RetentionGuard",
    "RetentionPolicyRepositoryPort",
    "StorageHoldRepositoryPort",
]
