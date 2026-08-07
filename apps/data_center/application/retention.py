"""Application ports for retention, holds and verified archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from apps.data_center.domain.raw_landing import RawPayload, raw_payload_record_digest
from apps.data_center.domain.retention import (
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanDecision,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
    retention_plan_snapshot_digest,
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


class ArchiveCoveragePort(Protocol):
    """Current byte-backed exact archive coverage used by deletion."""

    def has_verified_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
    ) -> bool: ...

    def verified_archive_id_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
        required_archive_id: str | None = None,
    ) -> str | None: ...


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

    def get_by_id(self, payload_id: str) -> RawPayload | None: ...

    def delete_if_matches(
        self,
        payload: RawPayload,
        *,
        expected_record_digest: str,
        now: datetime,
    ) -> int: ...


class RetentionRunRepositoryPort(Protocol):
    """Persistence port for append-only retention run evidence."""

    def save(self, run: RetentionRun) -> RetentionRun: ...


class RetentionPlanRepositoryPort(Protocol):
    """Persistence and single-writer claim port for exact retention plans."""

    def get_by_operation_id(
        self, operation_id: str
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]] | None: ...

    def create(
        self, plan: RetentionPlan, members: tuple[RetentionPlanMember, ...]
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]]: ...

    def claim(
        self,
        plan_id: str,
        *,
        operation_id: str,
        now: datetime,
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...], bool]: ...

    def save_member(self, plan_id: str, member: RetentionPlanMember) -> RetentionPlanMember: ...

    def finish(self, plan: RetentionPlan) -> RetentionPlan: ...


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
class RetentionPlanResult:
    """Planning response containing the exact persisted snapshot identifier."""

    outcome: str
    reason: str
    plan: RetentionPlan | None = None
    replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return the stable Celery planning contract."""

        plan = self.plan
        return {
            "success": self.outcome in {"success", "noop"},
            "outcome": self.outcome,
            "reason": self.reason,
            "plan_run_id": plan.plan_id if plan is not None else None,
            "plan_operation_id": plan.operation_id if plan is not None else None,
            "dataset_key": plan.dataset_key if plan is not None else None,
            "policy_id": plan.policy_id if plan is not None else None,
            "policy_version": plan.policy_version if plan is not None else None,
            "requested": plan.requested if plan is not None else 0,
            "succeeded": plan.planned if plan is not None else 0,
            "failed": 0,
            "stored": plan.candidates if plan is not None else 0,
            "candidates": plan.candidates if plan is not None else 0,
            "planned": plan.planned if plan is not None else 0,
            "held": plan.held if plan is not None else 0,
            "blocked": plan.blocked if plan is not None else 0,
            "bytes_planned": plan.bytes_planned if plan is not None else 0,
            "deleted": 0,
            "bytes_deleted": 0,
            "candidate_digest": plan.snapshot_digest if plan is not None else None,
            "cutoff": plan.cutoff.isoformat() if plan is not None else None,
            "plan_created_at": plan.created_at.isoformat() if plan is not None else None,
            "plan_expires_at": plan.expires_at.isoformat() if plan is not None else None,
            "plan_state": plan.status.value if plan is not None else None,
            "count_unit": "raw_payload",
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class RetentionEnforcementResult:
    """Stable result of consuming one exact persisted retention plan."""

    plan: RetentionPlan
    replayed: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return the stable Celery enforcement contract."""

        return {
            "success": self.plan.outcome in {"success", "noop"},
            "outcome": self.plan.outcome,
            "reason": self.plan.reason,
            "plan_run_id": self.plan.plan_id,
            "operation_id": self.plan.enforce_operation_id,
            "dataset_key": self.plan.dataset_key,
            "policy_version": self.plan.policy_version,
            "requested": self.plan.planned,
            "succeeded": self.plan.deleted,
            "failed": self.plan.failed,
            "stored": 0,
            "candidates": self.plan.candidates,
            "planned": self.plan.planned,
            "deleted": self.plan.deleted,
            "blocked": self.plan.execution_blocked,
            "bytes_deleted": self.plan.bytes_deleted,
            "candidate_digest": self.plan.snapshot_digest,
            "plan_state": self.plan.status.value,
            "count_unit": "raw_payload",
            "replayed": self.replayed,
        }


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
        archives: ArchiveCoveragePort,
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
        planned = 0
        deleted = 0
        held = 0
        blocked = 0
        bytes_planned = 0
        bytes_deleted = 0
        retention_blocked = 0
        delete_conflicts = 0
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
            if not self._archives.has_verified_for_payload(row, now=moment):
                blocked += 1
                continue
            if dry_run:
                planned += 1
                bytes_planned += payload_size
            else:
                deleted_count = self._candidates.delete_if_matches(
                    row,
                    expected_record_digest=raw_payload_record_digest(row),
                    now=moment,
                )
                deleted += deleted_count
                if deleted_count > 0:
                    bytes_deleted += payload_size
                else:
                    blocked += 1
                    delete_conflicts += 1
        if delete_conflicts and deleted == 0 and planned == 0 and held == 0:
            outcome = "blocked"
            reason = "raw_payload_changed_before_delete"
        elif retention_blocked and deleted == 0 and planned == 0 and held == 0:
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


class CreateRetentionPlanUseCase:
    """Freeze one bounded candidate set before any destructive operation."""

    def __init__(
        self,
        policies: RetentionPolicyRepositoryPort,
        holds: StorageHoldRepositoryPort,
        archives: ArchiveCoveragePort,
        candidates: RetentionCandidateRepositoryPort,
        plans: RetentionPlanRepositoryPort,
    ) -> None:
        self._policies = policies
        self._guard = RetentionGuard(holds)
        self._archives = archives
        self._candidates = candidates
        self._plans = plans

    def execute(
        self,
        *,
        dataset_key: str,
        operation_id: str,
        limit: int = 100,
        now: datetime | None = None,
        ttl_hours: int = 24,
    ) -> RetentionPlanResult:
        """Create or replay an immutable exact-member plan."""

        if not dataset_key.strip() or not operation_id.strip():
            raise ValueError("dataset_key and operation_id are required")
        if isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        if isinstance(ttl_hours, bool) or not 1 <= ttl_hours <= 168:
            raise ValueError("ttl_hours must be between 1 and 168")
        existing = self._plans.get_by_operation_id(operation_id.strip())
        if existing is not None:
            plan, _ = existing
            if plan.dataset_key != dataset_key.strip() or plan.requested != limit:
                raise ValueError("retention_plan_operation_immutable_conflict")
            return RetentionPlanResult(
                outcome=plan.outcome,
                reason=plan.reason,
                plan=plan,
                replayed=True,
            )
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        policy = self._policies.get_active(dataset_key.strip())
        if policy is None:
            return RetentionPlanResult(
                outcome="blocked",
                reason="retention_policy_missing_or_inactive",
            )
        cutoff = moment - timedelta(days=policy.retention_days)
        rows = self._candidates.list_expired(
            dataset_key.strip(), before=cutoff, limit=limit, now=moment
        )
        members: list[RetentionPlanMember] = []
        for ordinal, row in enumerate(rows):
            archive_id: str | None = None
            if not self._guard.can_delete("raw_payload", row.payload_id, now=moment):
                decision = RetentionPlanDecision.HELD
            elif row.retention_until is not None and row.retention_until > moment:
                decision = RetentionPlanDecision.RETENTION_BLOCKED
            else:
                archive_id = self._archives.verified_archive_id_for_payload(row, now=moment)
                decision = (
                    RetentionPlanDecision.ELIGIBLE
                    if archive_id is not None
                    else RetentionPlanDecision.ARCHIVE_BLOCKED
                )
            members.append(
                RetentionPlanMember(
                    ordinal=ordinal,
                    payload_id=row.payload_id,
                    payload_hash=row.payload_hash,
                    record_digest=raw_payload_record_digest(row),
                    schema_fingerprint=row.schema_fingerprint,
                    fetched_at=row.fetched_at,
                    retention_until=row.retention_until,
                    size_bytes=int(row.payload_size_bytes),
                    decision=decision,
                    archive_id=archive_id,
                    execution=(
                        RetentionMemberExecution.PENDING
                        if decision is RetentionPlanDecision.ELIGIBLE
                        else RetentionMemberExecution.SKIPPED
                    ),
                )
            )
        frozen = tuple(members)
        planned = sum(member.decision is RetentionPlanDecision.ELIGIBLE for member in frozen)
        held = sum(member.decision is RetentionPlanDecision.HELD for member in frozen)
        blocked = len(frozen) - planned - held
        if not frozen:
            status = RetentionPlanStatus.EMPTY
            outcome = "noop"
            reason = "no_expired_raw_payloads"
        elif planned == 0:
            status = RetentionPlanStatus.BLOCKED
            outcome = "blocked"
            reason = "no_candidates_passed_retention_gates"
        elif held or blocked:
            status = RetentionPlanStatus.READY
            outcome = "partial"
            reason = "some_candidates_excluded_from_plan"
        else:
            status = RetentionPlanStatus.READY
            outcome = "success"
            reason = "retention_plan_created"
        plan = RetentionPlan(
            plan_id=str(uuid4()),
            operation_id=operation_id.strip(),
            dataset_key=dataset_key.strip(),
            policy_id=policy.policy_id,
            policy_version=policy.version,
            requested=limit,
            candidates=len(frozen),
            planned=planned,
            held=held,
            blocked=blocked,
            bytes_planned=sum(
                member.size_bytes
                for member in frozen
                if member.decision is RetentionPlanDecision.ELIGIBLE
            ),
            cutoff=cutoff,
            created_at=moment,
            expires_at=moment + timedelta(hours=ttl_hours),
            snapshot_digest=retention_plan_snapshot_digest(
                dataset_key=dataset_key.strip(),
                policy_id=policy.policy_id,
                policy_version=policy.version,
                cutoff=cutoff,
                members=frozen,
            ),
            status=status,
            outcome=outcome,
            reason=reason,
        )
        saved, _ = self._plans.create(plan, frozen)
        return RetentionPlanResult(outcome=saved.outcome, reason=saved.reason, plan=saved)


class EnforceRetentionPlanUseCase:
    """Consume only persisted eligible members from one claimed plan."""

    def __init__(
        self,
        policies: RetentionPolicyRepositoryPort,
        holds: StorageHoldRepositoryPort,
        archives: ArchiveCoveragePort,
        candidates: RetentionCandidateRepositoryPort,
        plans: RetentionPlanRepositoryPort,
    ) -> None:
        self._policies = policies
        self._guard = RetentionGuard(holds)
        self._archives = archives
        self._candidates = candidates
        self._plans = plans

    def execute(
        self,
        *,
        plan_id: str,
        operation_id: str,
        now: datetime | None = None,
    ) -> RetentionEnforcementResult:
        """Claim and enforce one plan with policy, hold, archive and raw CAS rechecks."""

        if not plan_id.strip() or not operation_id.strip():
            raise ValueError("plan_id and operation_id are required")
        moment = now or datetime.now(UTC)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        plan, members, replayed = self._plans.claim(
            plan_id.strip(), operation_id=operation_id.strip(), now=moment
        )
        if replayed:
            return RetentionEnforcementResult(plan=plan, replayed=True)
        if plan.status is not RetentionPlanStatus.ENFORCING:
            return RetentionEnforcementResult(plan=plan)
        active = self._policies.get_active(plan.dataset_key)
        if (
            active is None
            or active.policy_id != plan.policy_id
            or active.version != plan.policy_version
        ):
            finished = self._finish_blocked(
                plan, moment=moment, reason="retention_policy_changed_replan_required"
            )
            return RetentionEnforcementResult(plan=finished)
        expected_digest = retention_plan_snapshot_digest(
            dataset_key=plan.dataset_key,
            policy_id=plan.policy_id,
            policy_version=plan.policy_version,
            cutoff=plan.cutoff,
            members=members,
        )
        if expected_digest != plan.snapshot_digest:
            finished = self._finish_blocked(
                plan, moment=moment, reason="retention_plan_snapshot_digest_mismatch"
            )
            return RetentionEnforcementResult(plan=finished)
        deleted = sum(member.execution is RetentionMemberExecution.DELETED for member in members)
        execution_blocked = sum(
            member.execution is RetentionMemberExecution.BLOCKED for member in members
        )
        failed = sum(member.execution is RetentionMemberExecution.FAILED for member in members)
        bytes_deleted = sum(
            member.size_bytes
            for member in members
            if member.execution is RetentionMemberExecution.DELETED
        )
        for member in members:
            if (
                member.decision is not RetentionPlanDecision.ELIGIBLE
                or member.execution is not RetentionMemberExecution.PENDING
            ):
                continue
            current = self._candidates.get_by_id(member.payload_id)
            block_reason = ""
            if current is None or raw_payload_record_digest(current) != member.record_digest:
                block_reason = "raw_payload_changed_before_delete"
            elif not self._guard.can_delete("dataset", plan.dataset_key, now=moment):
                block_reason = "dataset_hold_added_after_plan"
            elif not self._guard.can_delete("retention_plan", plan.plan_id, now=moment):
                block_reason = "retention_plan_hold_added_after_plan"
            elif not self._guard.can_delete("raw_payload", member.payload_id, now=moment):
                block_reason = "raw_payload_hold_added_after_plan"
            elif member.archive_id is None or not self._guard.can_delete(
                "archive", member.archive_id, now=moment
            ):
                block_reason = "archive_hold_added_after_plan"
            elif (
                self._archives.verified_archive_id_for_payload(
                    current,
                    now=moment,
                    required_archive_id=member.archive_id,
                )
                != member.archive_id
            ):
                block_reason = "planned_archive_evidence_no_longer_valid"
            if block_reason:
                execution_blocked += 1
                self._plans.save_member(
                    plan.plan_id,
                    RetentionPlanMember(
                        **{
                            **member.__dict__,
                            "execution": RetentionMemberExecution.BLOCKED,
                            "execution_reason": block_reason,
                        }
                    ),
                )
                continue
            if current is None:
                raise AssertionError("retention current payload guard failed")
            try:
                count = self._candidates.delete_if_matches(
                    current,
                    expected_record_digest=member.record_digest,
                    now=moment,
                )
            except Exception:
                failed += 1
                self._plans.save_member(
                    plan.plan_id,
                    RetentionPlanMember(
                        **{
                            **member.__dict__,
                            "execution": RetentionMemberExecution.FAILED,
                            "execution_reason": "raw_payload_delete_failed",
                        }
                    ),
                )
                continue
            if count == 1:
                deleted += 1
                bytes_deleted += member.size_bytes
                self._plans.save_member(
                    plan.plan_id,
                    RetentionPlanMember(
                        **{
                            **member.__dict__,
                            "execution": RetentionMemberExecution.DELETED,
                            "execution_reason": "deleted",
                            "deleted_at": moment,
                        }
                    ),
                )
            else:
                execution_blocked += 1
                self._plans.save_member(
                    plan.plan_id,
                    RetentionPlanMember(
                        **{
                            **member.__dict__,
                            "execution": RetentionMemberExecution.BLOCKED,
                            "execution_reason": "raw_payload_changed_before_delete",
                        }
                    ),
                )
        if deleted == plan.planned:
            status = RetentionPlanStatus.COMPLETED
            outcome = "success"
            reason = "retention_plan_enforced"
        elif deleted > 0:
            status = RetentionPlanStatus.PARTIAL
            outcome = "partial"
            reason = "retention_plan_partially_enforced"
        elif failed > 0 and execution_blocked == 0:
            status = RetentionPlanStatus.FAILED
            outcome = "failed"
            reason = "retention_plan_enforcement_failed"
        else:
            status = RetentionPlanStatus.BLOCKED
            outcome = "blocked"
            reason = "retention_plan_enforcement_blocked"
        finished = self._plans.finish(
            RetentionPlan(
                **{
                    **plan.__dict__,
                    "status": status,
                    "outcome": outcome,
                    "deleted": deleted,
                    "execution_blocked": execution_blocked,
                    "failed": failed,
                    "bytes_deleted": bytes_deleted,
                    "finished_at": moment,
                    "reason": reason,
                }
            )
        )
        return RetentionEnforcementResult(plan=finished)

    def _finish_blocked(
        self, plan: RetentionPlan, *, moment: datetime, reason: str
    ) -> RetentionPlan:
        """Persist a whole-plan fail-closed terminal result."""

        return self._plans.finish(
            RetentionPlan(
                **{
                    **plan.__dict__,
                    "status": RetentionPlanStatus.BLOCKED,
                    "outcome": "blocked",
                    "execution_blocked": plan.planned,
                    "finished_at": moment,
                    "reason": reason,
                }
            )
        )


__all__ = [
    "ArchiveCoveragePort",
    "CreateRetentionPlanUseCase",
    "EnforceRetentionPlanUseCase",
    "RetentionCandidateRepositoryPort",
    "RetentionCleanupResult",
    "RetentionCleanupUseCase",
    "RetentionEnforcementResult",
    "RetentionGuard",
    "RetentionPlanRepositoryPort",
    "RetentionPlanResult",
    "RetentionPolicyRepositoryPort",
    "RetentionRunRepositoryPort",
    "StorageHoldRepositoryPort",
]
