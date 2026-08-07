"""Behavioral evidence for policy-gated raw retention tasks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from apps.data_center.application.retention import RetentionCleanupUseCase
from apps.data_center.application.tasks import (
    cleanup_expired_raw_payloads_task,
    enforce_retention_task,
    plan_retention_task,
    verify_archive_manifest_task,
    verify_storage_budget_task,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveState,
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionPolicy,
    RetentionRun,
)

NOW = datetime(2026, 8, 2, 5, 0, tzinfo=UTC)


class _Policies:
    def __init__(self, policy: RetentionPolicy | None) -> None:
        self.policy = policy

    def get_active(self, dataset_key: str) -> RetentionPolicy | None:
        return self.policy if self.policy and self.policy.dataset_key == dataset_key else None


class _Holds:
    def __init__(self, held: set[str] | None = None) -> None:
        self.held = held or set()

    def has_active_hold(
        self, resource_type: str, resource_key: str, *, now: datetime | None = None
    ) -> bool:
        return resource_key in self.held


class _Archives:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def has_verified_for_payload(self, payload: RawPayload, *, now: datetime | None = None) -> bool:
        return self.ready

    def verified_archive_id_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
        required_archive_id: str | None = None,
    ) -> str | None:
        del payload, now
        archive_id = "11111111-1111-1111-1111-111111111111"
        if not self.ready or (
            required_archive_id is not None and required_archive_id != archive_id
        ):
            return None
        return archive_id


class _Candidates:
    def __init__(self, rows: list[RawPayload]) -> None:
        self.rows = rows
        self.deleted: list[str] = []

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]:
        return [
            row
            for row in self.rows
            if row.dataset_key == dataset_key
            and row.fetched_at < before
            and (row.retention_until is None or now is None or row.retention_until <= now)
        ][:limit]

    def get_by_id(self, payload_id: str) -> RawPayload | None:
        return next((row for row in self.rows if row.payload_id == payload_id), None)

    def delete_if_matches(
        self,
        payload: RawPayload,
        *,
        expected_record_digest: str,
        now: datetime,
    ) -> int:
        del expected_record_digest, now
        self.deleted.append(payload.payload_id)
        return 1


class _FailingCandidates(_Candidates):
    def delete_if_matches(
        self,
        payload: RawPayload,
        *,
        expected_record_digest: str,
        now: datetime,
    ) -> int:
        del payload, expected_record_digest, now
        raise RuntimeError("delete unavailable")


class _BrokenArchives(_Archives):
    def verified_archive_id_for_payload(
        self,
        payload: RawPayload,
        *,
        now: datetime | None = None,
        required_archive_id: str | None = None,
    ) -> str | None:
        del payload, now, required_archive_id
        raise RuntimeError("archive unavailable")


class _Runs:
    def __init__(self) -> None:
        self.saved: list[RetentionRun] = []

    def save(self, run: RetentionRun) -> RetentionRun:
        self.saved.append(run)
        return run


class _Plans:
    def __init__(self) -> None:
        self.by_operation: dict[str, tuple[RetentionPlan, tuple[RetentionPlanMember, ...]]] = {}
        self.candidates: _Candidates | None = None

    def get_by_operation_id(
        self, operation_id: str
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]] | None:
        return self.by_operation.get(operation_id)

    def create(
        self, plan: RetentionPlan, members: tuple[RetentionPlanMember, ...]
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...]]:
        self.by_operation[plan.operation_id] = (plan, members)
        return plan, members

    def claim(
        self, plan_id: str, *, operation_id: str, now: datetime
    ) -> tuple[RetentionPlan, tuple[RetentionPlanMember, ...], bool]:
        del now
        key, (plan, members) = next(
            item for item in self.by_operation.items() if item[1][0].plan_id == plan_id
        )
        if plan.status in {
            RetentionPlanStatus.COMPLETED,
            RetentionPlanStatus.PARTIAL,
            RetentionPlanStatus.FAILED,
        }:
            return plan, members, plan.enforce_operation_id == operation_id
        claimed = replace(
            plan,
            status=RetentionPlanStatus.ENFORCING,
            enforce_operation_id=operation_id,
            outcome="",
            reason="",
        )
        self.by_operation[key] = (claimed, members)
        return claimed, members, False

    def save_member(self, plan_id: str, member: RetentionPlanMember) -> RetentionPlanMember:
        key, (plan, members) = next(
            item for item in self.by_operation.items() if item[1][0].plan_id == plan_id
        )
        updated = tuple(
            member if item.payload_id == member.payload_id else item for item in members
        )
        self.by_operation[key] = (plan, updated)
        return member

    def consume_member(
        self,
        plan_id: str,
        member: RetentionPlanMember,
        *,
        now: datetime,
    ) -> RetentionPlanMember:
        if self.candidates is None:
            raise RuntimeError("candidate repository missing")
        current = self.candidates.get_by_id(member.payload_id)
        if current is None:
            blocked = replace(
                member,
                execution=RetentionMemberExecution.BLOCKED,
                execution_reason="raw_payload_changed_before_delete",
            )
            return self.save_member(plan_id, blocked)
        count = self.candidates.delete_if_matches(
            current, expected_record_digest=member.record_digest, now=now
        )
        if count != 1:
            blocked = replace(
                member,
                execution=RetentionMemberExecution.BLOCKED,
                execution_reason="raw_payload_changed_before_delete",
            )
            return self.save_member(plan_id, blocked)
        deleted = replace(
            member,
            execution=RetentionMemberExecution.DELETED,
            execution_reason="deleted",
            deleted_at=now,
        )
        return self.save_member(plan_id, deleted)

    def finish(self, plan: RetentionPlan) -> RetentionPlan:
        key, (_, members) = next(
            item for item in self.by_operation.items() if item[1][0].plan_id == plan.plan_id
        )
        self.by_operation[key] = (plan, members)
        return plan


class _VerifiableArchives:
    def __init__(self, manifest: ArchiveManifest | None) -> None:
        self.manifest = manifest
        self.marked = False

    def get(self, archive_id: str) -> ArchiveManifest | None:
        if self.manifest is None or self.manifest.archive_id != archive_id:
            return None
        return self.manifest

    def mark_verified(
        self, archive_id: str, *, verified_at: datetime | None = None
    ) -> ArchiveManifest:
        if self.manifest is None or self.manifest.archive_id != archive_id:
            raise LookupError("archive not found")
        self.marked = True
        self.manifest = replace(
            self.manifest,
            state=ArchiveState.VERIFIED,
            verified_at=verified_at or NOW,
        )
        return self.manifest


def _archive_manifest() -> ArchiveManifest:
    return ArchiveManifest(
        archive_id=str(uuid4()),
        dataset_key="market.raw",
        object_count=2,
        size_bytes=256,
        location="s3://fixture/archive.tar.zst",
        checksum="sha256:archive",
        state=ArchiveState.EXPORTED,
        created_at=NOW,
    )


def _policy() -> RetentionPolicy:
    return RetentionPolicy(
        policy_id=str(uuid4()),
        dataset_key="market.raw",
        version=1,
        retention_days=30,
        active=True,
    )


def _payload(*, retention_until: datetime | None = None) -> RawPayload:
    return RawPayload(
        payload_id=str(uuid4()),
        dataset_key="market.raw",
        provider_name="fixture",
        payload_hash="sha256:payload",
        schema_fingerprint="sha256:schema",
        payload={"value": 1},
        fetched_at=NOW - timedelta(days=31),
        payload_size_bytes=128,
        retention_until=retention_until,
    )


def _patch_task_dependencies(
    monkeypatch,
    policies,
    holds,
    archives,
    candidates,
    runs,
    plans=None,
) -> None:  # type: ignore[no-untyped-def]
    resolved_plans = plans or _Plans()
    if isinstance(resolved_plans, _Plans):
        resolved_plans.candidates = candidates
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: {"state": "healthy"},
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository", lambda: policies
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_storage_hold_repository", lambda: holds
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_archive_coverage_gateway", lambda: archives
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_raw_landing_repository", lambda: candidates
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_run_repository", lambda: runs
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_plan_repository",
        lambda: resolved_plans,
    )


def test_retention_task_rejects_invalid_input_before_repositories() -> None:
    result = cleanup_expired_raw_payloads_task(dataset_key="", limit=100)
    assert result["outcome"] == "failed"
    assert result["deleted"] == 0


def test_retention_task_blocks_without_active_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(None), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_policy_missing_or_inactive"
    assert runs.saved[0].outcome == "blocked"


def test_legacy_cleanup_task_rejects_mutating_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be reached")),
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10, dry_run=False)

    assert result["outcome"] == "blocked"
    assert result["error"] == "legacy_cleanup_mutation_disabled_use_enforce"
    assert result["deleted"] == 0


def test_legacy_cleanup_task_returns_dry_run_preview(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "noop"
    assert result["planned"] == 1
    assert result["deleted"] == 0
    assert candidates.deleted == []
    assert runs.saved[0].dry_run is True


def test_retention_task_reports_partial_for_active_hold(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload()
    candidates = _Candidates([payload])
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds({payload.payload_id}),
        _Archives(True),
        candidates,
        _Runs(),
    )

    result = (
        RetentionCleanupUseCase(
            _Policies(_policy()), _Holds({payload.payload_id}), _Archives(True), candidates
        )
        .execute(dataset_key="market.raw", limit=10, dry_run=False)
        .to_dict()
    )

    assert result["outcome"] == "partial"
    assert result["held"] == 1
    assert result["deleted"] == 0


def test_retention_task_does_not_delete_before_row_retention_deadline(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload(retention_until=datetime.now(UTC) + timedelta(days=1))
    candidates = _Candidates([payload])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = (
        RetentionCleanupUseCase(_Policies(_policy()), _Holds(), _Archives(True), candidates, runs)
        .execute(dataset_key="market.raw", limit=10, dry_run=False)
        .to_dict()
    )

    assert result["outcome"] == "noop"
    assert result["deleted"] == 0
    assert candidates.deleted == []


class _UnsafeCandidates(_Candidates):
    """Legacy candidate adapter that ignores row-level retention deadlines."""

    def list_expired(
        self,
        dataset_key: str,
        *,
        before: datetime,
        limit: int,
        now: datetime | None = None,
    ) -> list[RawPayload]:
        del now
        return [
            row for row in self.rows if row.dataset_key == dataset_key and row.fetched_at < before
        ][:limit]


def test_retention_task_fails_closed_for_legacy_future_deadline_candidate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    payload = _payload(retention_until=datetime.now(UTC) + timedelta(days=1))
    candidates = _UnsafeCandidates([payload])
    runs = _Runs()
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, runs
    )

    result = (
        RetentionCleanupUseCase(_Policies(_policy()), _Holds(), _Archives(True), candidates, runs)
        .execute(dataset_key="market.raw", limit=10, dry_run=False)
        .to_dict()
    )

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_until_not_reached"
    assert result["blocked"] == 1
    assert result["deleted"] == 0
    assert candidates.deleted == []


def test_retention_task_reports_storage_evaluation_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("observer down")),
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be reached")),
    )

    result = cleanup_expired_raw_payloads_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_pressure_evaluation_failed"


def test_plan_retention_task_rejects_invalid_limit() -> None:
    result = plan_retention_task(dataset_key="market.raw", limit=0)

    assert result["outcome"] == "failed"
    assert result["operation"] == "plan"


def test_plan_retention_task_persists_exact_snapshot(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    plans = _Plans()
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds(),
        _Archives(True),
        candidates,
        _Runs(),
        plans,
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-1")

    assert result["outcome"] == "success"
    assert result["operation"] == "plan"
    assert result["planned"] == 1
    assert result["plan_run_id"]
    assert result["candidate_digest"]
    assert candidates.deleted == []


def test_plan_retention_task_reports_partial_exclusions(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rows = [_payload(), _payload()]
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds({rows[1].payload_id}),
        _Archives(True),
        _Candidates(rows),
        _Runs(),
        _Plans(),
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-partial")

    assert result["outcome"] == "partial"
    assert result["planned"] == 1
    assert result["held"] == 1


def test_plan_retention_task_reports_zero_output_as_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds(),
        _Archives(True),
        _Candidates([]),
        _Runs(),
        _Plans(),
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-empty")

    assert result["outcome"] == "noop"
    assert result["candidates"] == 0


def test_plan_retention_task_reports_complete_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds(),
        _BrokenArchives(True),
        _Candidates([_payload()]),
        _Runs(),
        _Plans(),
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-failed")

    assert result["outcome"] == "failed"
    assert result["error"] == "retention_plan_creation_failed"


def test_plan_retention_task_blocks_without_storage_policy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: {"state": "blocked", "reason": "storage_policy_missing"},
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.get_retention_policy_repository",
        lambda: (_ for _ in ()).throw(AssertionError("retention repository must not be reached")),
    )

    result = plan_retention_task(dataset_key="market.raw", limit=10)

    assert result["outcome"] == "blocked"
    assert result["error"] == "storage_policy_missing"


def test_enforce_retention_task_rejects_non_boolean_confirmation() -> None:
    result = enforce_retention_task(
        plan_run_id="plan", operation_id="run", confirm=1  # type: ignore[arg-type]
    )

    assert result["outcome"] == "failed"
    assert result["error"] == "confirm must be a boolean"


def test_enforce_retention_task_consumes_exact_plan_and_replays(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    plans = _Plans()
    policy = _policy()
    _patch_task_dependencies(
        monkeypatch, _Policies(policy), _Holds(), _Archives(True), candidates, _Runs(), plans
    )
    planned = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-success")

    result = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]), operation_id="enforce-success", confirm=True
    )
    replay = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]), operation_id="enforce-success", confirm=True
    )

    assert result["outcome"] == "success"
    assert result["deleted"] == 1
    assert replay["replayed"] is True
    assert candidates.deleted == [candidates.rows[0].payload_id]


def test_enforce_retention_task_reports_partial_drift(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload(), _payload()])
    plans = _Plans()
    policy = _policy()
    _patch_task_dependencies(
        monkeypatch, _Policies(policy), _Holds(), _Archives(True), candidates, _Runs(), plans
    )
    planned = plan_retention_task(dataset_key="market.raw", limit=10, operation_id="plan-drift")
    candidates.rows[1] = replace(candidates.rows[1], payload={"value": 2})

    result = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]), operation_id="enforce-drift", confirm=True
    )

    assert result["outcome"] == "partial"
    assert result["deleted"] == 1
    assert result["blocked"] == 1


def test_enforce_retention_task_blocks_policy_drift_without_delete(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    plans = _Plans()
    policies = _Policies(_policy())
    _patch_task_dependencies(
        monkeypatch, policies, _Holds(), _Archives(True), candidates, _Runs(), plans
    )
    planned = plan_retention_task(
        dataset_key="market.raw", limit=10, operation_id="plan-policy-drift"
    )
    policies.policy = _policy()

    result = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]),
        operation_id="enforce-policy-drift",
        confirm=True,
    )

    assert result["outcome"] == "blocked"
    assert result["reason"] == "retention_policy_changed_replan_required"
    assert candidates.deleted == []


def test_enforce_retention_task_rechecks_hold_and_pinned_archive(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload(), _payload()])
    plans = _Plans()
    holds = _Holds()
    archives = _Archives(True)
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), holds, archives, candidates, _Runs(), plans
    )
    planned = plan_retention_task(
        dataset_key="market.raw", limit=10, operation_id="plan-gate-drift"
    )
    holds.held.add(candidates.rows[0].payload_id)
    archives.ready = False

    result = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]),
        operation_id="enforce-gate-drift",
        confirm=True,
    )

    assert result["outcome"] == "blocked"
    assert result["blocked"] == 2
    assert candidates.deleted == []


def test_enforce_retention_task_reports_complete_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _FailingCandidates([_payload()])
    plans = _Plans()
    _patch_task_dependencies(
        monkeypatch,
        _Policies(_policy()),
        _Holds(),
        _Archives(True),
        candidates,
        _Runs(),
        plans,
    )
    planned = plan_retention_task(
        dataset_key="market.raw", limit=10, operation_id="plan-delete-failure"
    )

    result = enforce_retention_task(
        plan_run_id=str(planned["plan_run_id"]),
        operation_id="enforce-delete-failure",
        confirm=True,
    )

    assert result["outcome"] == "failed"
    assert result["failed"] == 1
    assert result["deleted"] == 0


def test_enforce_retention_task_requires_explicit_confirmation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidates = _Candidates([_payload()])
    _patch_task_dependencies(
        monkeypatch, _Policies(_policy()), _Holds(), _Archives(True), candidates, _Runs()
    )

    result = enforce_retention_task(plan_run_id="plan", operation_id="run")

    assert result["outcome"] == "blocked"
    assert result["error"] == "explicit_confirmation_required"
    assert candidates.deleted == []


def test_archive_verification_rejects_invalid_archive_id_before_repository(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.archive_tasks.get_archive_manifest_repository",
        lambda: (_ for _ in ()).throw(AssertionError("repository must not be reached")),
    )

    result = verify_archive_manifest_task(archive_id="")

    assert result["outcome"] == "failed"
    assert result["reason"] == "archive_id is required"


def test_archive_verification_blocks_without_configured_cold_store(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.archive_tasks.get_archive_manifest_repository",
        lambda: _VerifiableArchives(_archive_manifest()),
    )
    monkeypatch.setattr(
        "apps.data_center.application.archive_tasks.get_raw_archive_store",
        lambda: (_ for _ in ()).throw(RuntimeError("data_center_archive_root_not_configured")),
    )

    result = verify_archive_manifest_task(archive_id=str(uuid4()))

    assert result["outcome"] == "blocked"
    assert result["reason"] == "data_center_archive_root_not_configured"


def _patch_storage_probe(monkeypatch, pressure: dict[str, object]) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=100, used=20, free=80),
    )
    monkeypatch.setattr(
        "apps.data_center.application.tasks.evaluate_storage_pressure",
        lambda **_kwargs: pressure,
    )


def test_storage_budget_task_reports_healthy(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "healthy", "usage_ratio": 0.2})

    result = verify_storage_budget_task()

    assert result["outcome"] == "success"
    assert result["succeeded"] == 1
    assert result["failed"] == 0


def test_storage_budget_task_reports_warning_as_partial(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "warning", "usage_ratio": 0.8})

    result = verify_storage_budget_task()

    assert result["outcome"] == "partial"
    assert result["success"] is False
    assert result["succeeded"] == 1


def test_storage_budget_task_blocks_critical_pressure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_storage_probe(monkeypatch, {"state": "critical", "usage_ratio": 0.95})

    result = verify_storage_budget_task()

    assert result["outcome"] == "blocked"
    assert result["blocked"] == 1
    assert result["error"] == "storage_pressure_critical"


def test_storage_budget_task_reports_observer_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "apps.data_center.application.tasks.shutil.disk_usage",
        lambda _path: (_ for _ in ()).throw(OSError("mount unavailable")),
    )

    result = verify_storage_budget_task()

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_budget_verification_failed"


def test_storage_budget_task_rejects_non_string_path() -> None:
    result = verify_storage_budget_task(storage_path=1)  # type: ignore[arg-type]

    assert result["outcome"] == "failed"
    assert result["error"] == "storage_path must be a string"
