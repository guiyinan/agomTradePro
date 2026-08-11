"""Task Monitor contracts for technical state, business outcome, and heartbeat loss."""

import gzip
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.task_monitor.application import tasks
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.infrastructure.repositories import CeleryHealthChecker


def _record(*, status: TaskStatus = TaskStatus.STARTED, retries: int = 0) -> TaskExecutionRecord:
    started_at = timezone.now() - timedelta(seconds=3)
    return TaskExecutionRecord(
        task_id="task-1",
        task_name="demo.task",
        status=status,
        args=("a",),
        kwargs={"scope": "unit"},
        started_at=started_at,
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=retries,
        priority=TaskPriority.NORMAL,
        queue="default",
        worker="worker-1",
    )


class _Repository:
    def __init__(self, record: TaskExecutionRecord | None = None) -> None:
        self.record = record
        self.saved: list[TaskExecutionRecord] = []

    def get_by_task_id(self, _task_id: str) -> TaskExecutionRecord | None:
        return self.record

    def save(self, record: TaskExecutionRecord) -> str:
        self.saved.append(record)
        self.record = record
        return "saved"


@pytest.mark.parametrize("outcome", ["failed", "partial", "blocked"])
def test_postrun_business_outcome_overrides_celery_success(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    """A successful transport cannot hide a failed or incomplete business result."""

    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(
        tasks,
        "get_use_case",
        lambda: SimpleNamespace(execute=execute),
    )

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval={"outcome": outcome, "stored": 0},
        state="SUCCESS",
    )

    saved = execute.call_args.args[0]
    assert saved.status is TaskStatus.FAILURE
    assert outcome in saved.result


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("SUCCESS", TaskStatus.SUCCESS),
        ("FAILURE", TaskStatus.FAILURE),
        ("REVOKED", TaskStatus.REVOKED),
    ],
)
def test_postrun_preserves_terminal_technical_states(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    expected: TaskStatus,
) -> None:
    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval={"outcome": "success"},
        state=state,
    )

    assert execute.call_args.args[0].status is expected


def test_task_signal_lifecycle_records_start_retry_failure_and_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    execute = Mock(side_effect=lambda record: repository.save(record))
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))
    celery_task = SimpleNamespace(
        name="demo.task",
        request={"delivery_info": {"routing_key": "priority"}, "hostname": "worker-a"},
    )

    tasks.task_prerun_handler(
        task_id="task-1",
        task=celery_task,
        args=(1,),
        kwargs={"mode": "safe"},
    )
    assert repository.record is not None
    assert repository.record.status is TaskStatus.STARTED

    tasks.task_retry_handler(
        task_id="task-1",
        reason="temporary",
        einfo=SimpleNamespace(traceback="retry trace"),
    )
    assert repository.record.status is TaskStatus.RETRY
    assert repository.record.retries == 1

    tasks.task_failure_handler(
        task_id="task-1",
        einfo=SimpleNamespace(exception=RuntimeError("boom"), traceback="failure trace"),
    )
    assert repository.record.status is TaskStatus.FAILURE
    assert repository.record.exception == "RuntimeError"

    tasks.task_revoked_handler(task_id="task-1", terminated=True, expired=False)
    assert repository.record.status is TaskStatus.REVOKED
    assert "terminated=True" in (repository.record.exception or "")


def test_signal_handlers_ignore_missing_identity_or_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)

    tasks.task_prerun_handler(task_id=None, task=None)
    tasks.task_postrun_handler(task_id="missing", task=SimpleNamespace(name="demo.task"))
    tasks.task_failure_handler(task_id="missing", exception=RuntimeError("ignored"))
    tasks.task_retry_handler(task_id="missing")
    tasks.task_revoked_handler(task_id="missing")

    assert repository.saved == []


def test_missing_worker_heartbeat_marks_celery_health_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachable transports without a worker heartbeat are still unavailable."""

    inspect = SimpleNamespace(
        active=Mock(return_value={}),
        scheduled=Mock(return_value={}),
        reserved=Mock(return_value={}),
    )
    app = SimpleNamespace(
        conf=SimpleNamespace(broker_url="memory://", result_backend="cache+memory://"),
        connection_for_read=lambda: SimpleNamespace(connect=lambda: None),
        backend=object(),
        control=SimpleNamespace(inspect=lambda timeout: inspect),
    )
    checker = CeleryHealthChecker(app)
    monkeypatch.setattr(checker, "_preflight_transport_endpoint", lambda _url: None)

    result = checker.check_health()

    assert result.broker_reachable is True
    assert result.backend_reachable is True
    assert result.active_workers == []
    assert result.is_healthy is False


def test_worker_heartbeat_and_queue_counts_produce_healthy_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspect = SimpleNamespace(
        active=Mock(return_value={"worker-a": [{"id": "running"}]}),
        scheduled=Mock(return_value={"worker-a": [{"id": "scheduled"}]}),
        reserved=Mock(return_value={"worker-a": [{"id": "reserved"}]}),
    )
    app = SimpleNamespace(
        conf=SimpleNamespace(broker_url="memory://", result_backend="cache+memory://"),
        connection_for_read=lambda: SimpleNamespace(connect=lambda: None),
        backend=object(),
        control=SimpleNamespace(inspect=lambda timeout: inspect),
    )
    checker = CeleryHealthChecker(app)
    monkeypatch.setattr(checker, "_preflight_transport_endpoint", lambda _url: None)

    result = checker.check_health()

    assert result.is_healthy is True
    assert result.active_tasks_count == 1
    assert result.scheduled_tasks_count == 1
    assert result.pending_tasks_count == 1


def test_backup_verification_distinguishes_missing_empty_valid_and_corrupt(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.sql"
    assert tasks.verify_backup_task.run(str(missing))["outcome"] == "failed"

    empty = tmp_path / "empty.sql"
    empty.write_bytes(b"")
    assert tasks.verify_backup_task.run(str(empty))["reason"] == "backup_file_empty"

    valid = tmp_path / "valid.sql.gz"
    with gzip.open(valid, "wb") as stream:
        stream.write(b"SELECT 1;")
    assert tasks.verify_backup_task.run(str(valid))["outcome"] == "success"

    corrupt = tmp_path / "corrupt.sql.gz"
    corrupt.write_bytes(b"not gzip")
    assert tasks.verify_backup_task.run(str(corrupt))["outcome"] == "failed"


def test_cleanup_task_reports_deleted_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks, "get_repository", lambda: object())
    monkeypatch.setattr(
        "apps.task_monitor.application.use_cases.CleanupOldRecordsUseCase",
        lambda repository: SimpleNamespace(execute=lambda *, days_to_keep: days_to_keep + 2),
    )

    assert tasks.cleanup_old_task_records.run(days_to_keep=30) == {
        "status": "success",
        "outcome": "success",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 0,
        "deleted_count": 32,
        "days_to_keep": 30,
    }


def test_cleanup_task_reports_noop_and_stable_input_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(
        "apps.task_monitor.application.use_cases.CleanupOldRecordsUseCase",
        lambda repository: SimpleNamespace(execute=lambda *, days_to_keep: 0),
    )

    assert tasks.cleanup_old_task_records.run(days_to_keep=30) == {
        "status": "success",
        "outcome": "noop",
        "success": True,
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 0,
        "deleted_count": 0,
        "days_to_keep": 30,
    }
    assert tasks.cleanup_old_task_records.run(days_to_keep=True) == {
        "status": "error",
        "outcome": "failed",
        "success": False,
        "requested": 1,
        "succeeded": 0,
        "failed": 1,
        "stored": 0,
        "deleted_count": 0,
        "days_to_keep": True,
        "error": "days_to_keep must be an integer between 1 and 3650",
    }
