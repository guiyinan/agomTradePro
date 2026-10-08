"""Fail-closed Task Monitor orphan reconciliation contracts."""

import json
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.task_monitor.application.orphan_reconciliation import (
    ReconcileOrphanedTaskRecordsUseCase,
)
from apps.task_monitor.application.use_cases import GetTaskStatusUseCase, ListTasksUseCase
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskOrphanAttemptEvidence,
    TaskOrphanClusterSnapshot,
    TaskOrphanLeaseState,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.infrastructure.models import TaskExecutionModel
from apps.task_monitor.infrastructure.orphan_evidence import CeleryTaskOrphanEvidenceProvider
from apps.task_monitor.infrastructure.repositories import DjangoTaskRecordRepository
from apps.task_monitor.interface.serializers import TaskStatusSerializer

_TASK_ID = "orphan-candidate"
_ATTEMPT_ID = "attempt-current"
_WORKER = "worker-a@example"
_HARD_LIMIT_SECONDS = 300
_VISIBILITY_SECONDS = 7_200
_GRACE_SECONDS = 300
_FINANCIAL_TASK_NAME = "data_center.refresh_financial_publications_batch"


class _EvidenceProvider:
    """Deterministic evidence provider for isolated unit tests."""

    def __init__(
        self,
        snapshot: TaskOrphanClusterSnapshot,
        evidence: TaskOrphanAttemptEvidence,
        *,
        before_evidence: Callable[[TaskExecutionRecord], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.evidence = evidence
        self.before_evidence = before_evidence
        self.snapshot_calls = 0
        self.evidence_calls = 0

    def capture_cluster_snapshot(self) -> TaskOrphanClusterSnapshot:
        self.snapshot_calls += 1
        return self.snapshot

    def get_attempt_evidence(
        self,
        record: TaskExecutionRecord,
        *,
        snapshot: TaskOrphanClusterSnapshot,
    ) -> TaskOrphanAttemptEvidence:
        del snapshot
        self.evidence_calls += 1
        if self.before_evidence is not None:
            self.before_evidence(record)
        return self.evidence


def _make_snapshot(
    *,
    observed_at=None,
    complete: bool = True,
    ready_message_count: int | None = 0,
    active_task_ids: tuple[str, ...] | None = (),
    reserved_task_ids: tuple[str, ...] | None = (),
    scheduled_task_ids: tuple[str, ...] | None = (),
    responding_worker_names: tuple[str, ...] | None = ("worker-b@example",),
    grace_seconds: int | None = _GRACE_SECONDS,
    visibility_timeout_seconds: int | None = _VISIBILITY_SECONDS,
) -> TaskOrphanClusterSnapshot:
    now = observed_at or timezone.now()
    return TaskOrphanClusterSnapshot(
        observed_at=now,
        complete=complete,
        broker_visibility_timeout_seconds=visibility_timeout_seconds,
        grace_seconds=grace_seconds,
        ready_message_count=ready_message_count,
        active_task_ids=active_task_ids,
        reserved_task_ids=reserved_task_ids,
        scheduled_task_ids=scheduled_task_ids,
        responding_worker_names=responding_worker_names,
        managed_queue_count=2,
    )


def _make_evidence(
    *,
    hard_limit_seconds: int | None = _HARD_LIMIT_SECONDS,
    backend_state: str | None = "PENDING",
    lease_state: TaskOrphanLeaseState = TaskOrphanLeaseState.ABSENT,
) -> TaskOrphanAttemptEvidence:
    return TaskOrphanAttemptEvidence(
        hard_time_limit_seconds=hard_limit_seconds,
        backend_state=backend_state,
        lease_state=lease_state,
        lease_evidence_code="test_domain_lease_v1",
    )


def _create_record(
    *,
    task_id: str = _TASK_ID,
    status: str = "started",
    attempt_id: str | None = _ATTEMPT_ID,
    worker: str | None = _WORKER,
    retries: int = 0,
    started_at=None,
) -> TaskExecutionModel:
    start = started_at or timezone.now() - timedelta(
        seconds=_HARD_LIMIT_SECONDS + _VISIBILITY_SECONDS + _GRACE_SECONDS + 60
    )
    return TaskExecutionModel.objects.create(
        task_id=task_id,
        task_name="demo.task",
        status=status,
        attempt_id=attempt_id,
        args=["sensitive-arg"],
        kwargs={"token": "never-persist-this"},
        started_at=start,
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=retries,
        worker=worker,
        queue="celery",
    )


def _run_reconciliation(
    evidence_provider: _EvidenceProvider,
) -> object:
    return ReconcileOrphanedTaskRecordsUseCase(
        repository=DjangoTaskRecordRepository(),
        evidence_provider=evidence_provider,
    ).execute()


def test_confirmed_orphan_is_atomically_timed_out_with_safe_versioned_evidence(db) -> None:
    row = _create_record()
    snapshot = _make_snapshot()
    provider = _EvidenceProvider(snapshot, _make_evidence())

    result = _run_reconciliation(provider)

    row.refresh_from_db()
    assert result.checked_count == 1
    assert result.timed_out_count == 1
    assert result.deferred_count == 0
    assert row.status == TaskStatus.TIMEOUT.value
    assert row.exception == "TASK_ORPHAN_TIMEOUT"
    assert row.finished_at == snapshot.observed_at
    payload = json.loads(row.result or "{}")
    assert payload["outcome"] == "failed"
    assert payload["error_code"] == "TASK_ORPHAN_TIMEOUT"
    assert payload["requested"] is None
    assert payload["succeeded"] is None
    assert payload["failed"] is None
    assert payload["stored"] is None
    assert payload["counts_unavailable"] is True
    assert payload["orphan_evidence"]["evidence_version"] == "task_monitor_orphan_v1"
    assert payload["orphan_evidence"]["queue_evidence_code"] == (
        "complete_all_managed_queues_empty"
    )
    assert payload["orphan_evidence"]["managed_queue_count"] == 2
    assert payload["orphan_evidence"]["attempt_id_sha256"]
    assert "sensitive-arg" not in row.result
    assert "never-persist-this" not in row.result
    projected = GetTaskStatusUseCase(repository=DjangoTaskRecordRepository()).execute(
        task_id=_TASK_ID
    )
    assert projected is not None
    assert projected.requested is None
    assert projected.counts_unavailable is True
    assert TaskStatusSerializer(projected).data["counts_unavailable"] is True
    assert _run_reconciliation(provider).timed_out_count == 0


@pytest.mark.parametrize(
    "case",
    [
        "backend_success",
        "backend_failure",
        "backend_revoked",
        "active",
        "reserved",
        "scheduled",
        "ready_queue_nonempty",
        "original_worker_online",
        "domain_lease_active",
        "domain_lease_unknown",
        "before_deadline",
        "missing_hard_limit",
        "missing_backend_state",
        "missing_attempt",
        "missing_worker",
        "retry_attempt_without_attempt_start_time",
        "incomplete_snapshot",
    ],
)
def test_any_live_or_incomplete_evidence_preserves_started_record(db, case: str) -> None:
    started_at = None
    if case == "before_deadline":
        started_at = timezone.now() - timedelta(
            seconds=_HARD_LIMIT_SECONDS + _VISIBILITY_SECONDS + _GRACE_SECONDS - 1
        )
    row = _create_record(
        attempt_id=None if case == "missing_attempt" else _ATTEMPT_ID,
        worker=None if case == "missing_worker" else _WORKER,
        retries=1 if case == "retry_attempt_without_attempt_start_time" else 0,
        started_at=started_at,
    )
    snapshot = _make_snapshot(
        complete=case != "incomplete_snapshot",
        ready_message_count=1 if case == "ready_queue_nonempty" else 0,
        active_task_ids=(_TASK_ID,) if case == "active" else (),
        reserved_task_ids=(_TASK_ID,) if case == "reserved" else (),
        scheduled_task_ids=(_TASK_ID,) if case == "scheduled" else (),
        responding_worker_names=(
            (_WORKER, "worker-b@example")
            if case == "original_worker_online"
            else ("worker-b@example",)
        ),
        observed_at=(
            timezone.now() if case == "before_deadline" else timezone.now() + timedelta(seconds=1)
        ),
    )
    evidence = _make_evidence(
        hard_limit_seconds=None if case == "missing_hard_limit" else _HARD_LIMIT_SECONDS,
        backend_state=(
            "SUCCESS"
            if case == "backend_success"
            else (
                "FAILURE"
                if case == "backend_failure"
                else (
                    "REVOKED"
                    if case == "backend_revoked"
                    else None if case == "missing_backend_state" else "PENDING"
                )
            )
        ),
        lease_state=(
            TaskOrphanLeaseState.ACTIVE
            if case == "domain_lease_active"
            else (
                TaskOrphanLeaseState.UNKNOWN
                if case == "domain_lease_unknown"
                else TaskOrphanLeaseState.ABSENT
            )
        ),
    )
    provider = _EvidenceProvider(snapshot, evidence)

    result = _run_reconciliation(provider)

    row.refresh_from_db()
    assert result.timed_out_count == 0
    assert row.status == TaskStatus.STARTED.value


def test_pending_records_are_never_inferred_orphan_from_absent_worker_evidence(db) -> None:
    row = _create_record(status="pending", attempt_id=None, worker=None)
    provider = _EvidenceProvider(_make_snapshot(), _make_evidence())

    result = _run_reconciliation(provider)

    row.refresh_from_db()
    assert result.checked_count == 0
    assert provider.snapshot_calls == 0
    assert row.status == TaskStatus.PENDING.value


def test_attempt_change_during_evidence_collection_fails_compare_and_set(db) -> None:
    row = _create_record()

    def replace_attempt(_record: TaskExecutionRecord) -> None:
        TaskExecutionModel.objects.filter(pk=row.pk, status="started").update(
            attempt_id="replacement-attempt"
        )

    provider = _EvidenceProvider(
        _make_snapshot(),
        _make_evidence(),
        before_evidence=replace_attempt,
    )

    result = _run_reconciliation(provider)

    row.refresh_from_db()
    assert result.timed_out_count == 0
    assert row.status == TaskStatus.STARTED.value
    assert row.attempt_id == "replacement-attempt"


def test_late_terminal_state_wins_over_orphan_compare_and_set(db) -> None:
    row = _create_record()

    def complete_attempt(_record: TaskExecutionRecord) -> None:
        TaskExecutionModel.objects.filter(pk=row.pk, status="started").update(
            status="success",
            result='{"outcome":"success"}',
        )

    provider = _EvidenceProvider(
        _make_snapshot(),
        _make_evidence(),
        before_evidence=complete_attempt,
    )

    result = _run_reconciliation(provider)

    row.refresh_from_db()
    assert result.timed_out_count == 0
    assert row.status == TaskStatus.SUCCESS.value
    assert row.result == '{"outcome":"success"}'


def test_read_only_task_queries_do_not_capture_orphan_evidence(db, monkeypatch) -> None:
    _create_record()
    repository = DjangoTaskRecordRepository()
    capture = Mock(side_effect=AssertionError("read query attempted reconciliation"))
    monkeypatch.setattr(
        "apps.task_monitor.application.repository_provider.get_task_orphan_evidence_provider",
        capture,
    )

    assert GetTaskStatusUseCase(repository=repository).execute(task_id=_TASK_ID) is not None
    assert ListTasksUseCase(repository=repository).execute(limit=10)
    capture.assert_not_called()


def test_celery_provider_requires_complete_read_only_queue_and_worker_snapshot() -> None:
    queue_declare = Mock(return_value=SimpleNamespace(message_count=0))
    channel = SimpleNamespace(queue_declare=queue_declare, close=Mock())
    connection = SimpleNamespace(channel=Mock(return_value=channel), release=Mock())
    inspect = SimpleNamespace(
        ping=Mock(return_value={"worker-b@example": {"ok": "pong"}}),
        active=Mock(return_value={"worker-b@example": []}),
        reserved=Mock(return_value={"worker-b@example": []}),
        scheduled=Mock(return_value={"worker-b@example": []}),
    )
    app = SimpleNamespace(
        conf=SimpleNamespace(
            broker_transport_options={"visibility_timeout": _VISIBILITY_SECONDS},
            task_queues=(SimpleNamespace(name="celery"), SimpleNamespace(name="priority")),
            task_time_limit=None,
        ),
        tasks={"demo.task": SimpleNamespace(time_limit=_HARD_LIMIT_SECONDS)},
        connection_for_read=Mock(return_value=connection),
        control=SimpleNamespace(inspect=Mock(return_value=inspect)),
        backend=SimpleNamespace(get_task_meta=Mock(return_value={"status": "PENDING"})),
    )
    provider = CeleryTaskOrphanEvidenceProvider(celery_app=app)

    snapshot = provider.capture_cluster_snapshot()
    evidence = provider.get_attempt_evidence(
        TaskExecutionRecord(
            task_id=_TASK_ID,
            task_name="demo.task",
            status=TaskStatus.STARTED,
            args=(),
            kwargs={},
            started_at=timezone.now() - timedelta(hours=3),
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue="celery",
            worker=_WORKER,
            attempt_id=_ATTEMPT_ID,
        ),
        snapshot=snapshot,
    )

    assert snapshot.complete is True
    assert snapshot.ready_message_count == 0
    assert snapshot.responding_worker_names == ("worker-b@example",)
    assert evidence.hard_time_limit_seconds == _HARD_LIMIT_SECONDS
    assert evidence.backend_state == "PENDING"
    assert evidence.lease_state is TaskOrphanLeaseState.NOT_REQUIRED
    assert queue_declare.call_count == 2
    assert all(call.kwargs["passive"] is True for call in queue_declare.call_args_list)
    channel.close.assert_called_once()
    connection.release.assert_called_once()

    queue_declare.return_value = SimpleNamespace()
    incomplete_snapshot = provider.capture_cluster_snapshot()
    assert incomplete_snapshot.complete is False
    assert incomplete_snapshot.ready_message_count is None


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        ("workflow-current", TaskOrphanLeaseState.ACTIVE),
        ("workflow-replacement", TaskOrphanLeaseState.ABSENT),
        (None, TaskOrphanLeaseState.ABSENT),
    ],
)
def test_financial_domain_lease_is_checked_against_exact_workflow_owner(
    owner: str | None,
    expected: TaskOrphanLeaseState,
) -> None:
    from apps.data_center.infrastructure.task_monitor_lease_probe import (
        DjangoDataCenterTaskLeaseProbe,
    )

    cache_backend = SimpleNamespace(get=lambda _key: owner)
    app = SimpleNamespace(
        conf=SimpleNamespace(
            broker_transport_options={"visibility_timeout": _VISIBILITY_SECONDS},
            task_queues=(SimpleNamespace(name="celery"),),
            task_time_limit=None,
        ),
        tasks={_FINANCIAL_TASK_NAME: SimpleNamespace(time_limit=3_600)},
        backend=SimpleNamespace(get_task_meta=Mock(return_value={"status": "PENDING"})),
    )
    provider = CeleryTaskOrphanEvidenceProvider(
        celery_app=app,
        domain_lease_probes=(DjangoDataCenterTaskLeaseProbe(cache_backend=cache_backend),),
    )
    record = TaskExecutionRecord(
        task_id=_TASK_ID,
        task_name=_FINANCIAL_TASK_NAME,
        status=TaskStatus.STARTED,
        args=(),
        kwargs={"workflow_id": "workflow-current"},
        started_at=timezone.now() - timedelta(hours=3),
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="celery",
        worker=_WORKER,
        attempt_id=_ATTEMPT_ID,
    )

    evidence = provider.get_attempt_evidence(record, snapshot=_make_snapshot())

    assert evidence.lease_state is expected
    assert evidence.lease_evidence_code == (
        "financial_refresh_workflow_lease_present"
        if expected is TaskOrphanLeaseState.ACTIVE
        else "financial_refresh_workflow_lease_absent"
    )
    safe_evidence = evidence.to_safe_dict(record=record, snapshot=_make_snapshot())
    assert "workflow-current" not in json.dumps(safe_evidence)


@pytest.mark.parametrize("workflow_id", [None, 7, "", "bad workflow", "x" * 65])
def test_financial_domain_lease_rejects_missing_or_malformed_workflow_id(
    workflow_id: object,
) -> None:
    from apps.data_center.infrastructure.task_monitor_lease_probe import (
        DjangoDataCenterTaskLeaseProbe,
    )

    cache_backend = SimpleNamespace(
        get=Mock(side_effect=AssertionError("invalid workflow id must not read the lease"))
    )
    probe = DjangoDataCenterTaskLeaseProbe(cache_backend=cache_backend)

    evidence = probe.get_lease_evidence(
        task_name=_FINANCIAL_TASK_NAME,
        task_kwargs={"workflow_id": workflow_id},
    )

    assert evidence.state.value == "unknown"
    assert evidence.evidence_code == "financial_refresh_workflow_id_unavailable"
    cache_backend.get.assert_not_called()
