"""Task Monitor contracts for technical state, business outcome, and heartbeat loss."""

import gzip
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.task_monitor.application import tasks
from apps.task_monitor.application.dtos import task_status_response
from apps.task_monitor.application.tracking import (
    TaskProgress,
    TaskProgressPhase,
    record_task_progress,
)
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)
from apps.task_monitor.infrastructure.repositories import (
    CeleryHealthChecker,
    DjangoTaskRecordRepository,
)
from apps.task_monitor.interface.serializers import TaskStatusSerializer


def _record(
    *,
    status: TaskStatus = TaskStatus.STARTED,
    retries: int = 0,
    attempt_id: str | None = None,
) -> TaskExecutionRecord:
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
        attempt_id=attempt_id,
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

    def save_if_attempt(
        self,
        record: TaskExecutionRecord,
        *,
        expected_attempt_id: str,
    ) -> str | None:
        if self.record is None or self.record.attempt_id != expected_attempt_id:
            return None
        return self.save(record)

    def update_result_if_status(
        self,
        *,
        task_id: str,
        result: str,
        expected_status: TaskStatus,
        expected_attempt_id: str | None = None,
    ) -> bool:
        if (
            self.record is None
            or self.record.task_id != task_id
            or self.record.status is not expected_status
            or (expected_attempt_id is not None and self.record.attempt_id != expected_attempt_id)
        ):
            return False
        self.record = replace(self.record, result=result)
        return True


def test_task_progress_updates_only_active_record_and_postrun_replaces_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live progress is safe metadata and terminal task outcome remains authoritative."""

    repository = _Repository(_record())
    monkeypatch.setattr(
        "apps.task_monitor.application.tracking.get_task_record_repository",
        lambda: repository,
    )

    progress = TaskProgress(
        phase="scope",
        requested=1,
        succeeded=0,
        failed=0,
        stored=None,
        count_unit="universe_sync_operation",
        phase_results=(
            TaskProgressPhase(
                phase="scope",
                requested=1,
                succeeded=0,
                failed=0,
                stored=None,
                count_unit="universe_sync_operation",
            ),
        ),
    )

    assert record_task_progress(task_id="task-1", progress=progress) is True
    assert repository.record is not None
    assert json.loads(repository.record.result or "{}") == {
        "count_unit": "universe_sync_operation",
        "failed": 0,
        "phase": "scope",
        "phase_results": [
            {
                "count_unit": "universe_sync_operation",
                "failed": 0,
                "phase": "scope",
                "requested": 1,
                "stored": None,
                "stored_count_unit": None,
                "succeeded": 0,
            }
        ],
        "requested": 1,
        "stored": None,
        "stored_count_unit": None,
        "succeeded": 0,
    }

    response = task_status_response(repository.record)
    assert response.outcome is None
    assert response.phase == "scope"
    assert response.requested == 1
    assert response.stored is None

    terminal = replace(repository.record, status=TaskStatus.SUCCESS)
    repository.record = terminal
    assert record_task_progress(task_id="task-1", progress=progress) is False
    assert repository.record is terminal


def test_started_task_runtime_is_derived_from_started_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active runtime stays live without writing elapsed-time snapshots to storage."""

    record = _record()
    assert record.started_at is not None
    observed_at = record.started_at + timedelta(seconds=42)
    monkeypatch.setattr(
        "apps.task_monitor.application.dtos.timezone.now",
        lambda: observed_at,
    )

    assert task_status_response(record).runtime_seconds == 42.0
    assert record.runtime_seconds is None

    completed = replace(record, status=TaskStatus.SUCCESS, runtime_seconds=9.5)
    assert task_status_response(completed).runtime_seconds == 9.5


def test_progress_repository_update_is_conditioned_on_started_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The progress write cannot overwrite a terminal Task Monitor record."""

    from apps.task_monitor.infrastructure import repositories

    update = Mock(return_value=1)
    filter_records = Mock(return_value=SimpleNamespace(update=update))
    monkeypatch.setattr(
        repositories.TaskExecutionModel,
        "objects",
        SimpleNamespace(filter=filter_records),
    )

    updated = DjangoTaskRecordRepository().update_result_if_status(
        task_id="task-1",
        result='{"phase":"quote"}',
        expected_status=TaskStatus.STARTED,
    )

    assert updated is True
    filter_records.assert_called_once_with(task_id="task-1", status="started")
    update.assert_called_once_with(result='{"phase":"quote"}')


def test_duplicate_prerun_does_not_replace_live_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broker redelivery cannot reset the original start or live result."""

    original = _record(attempt_id="attempt-original")
    original_result = '{"phase":"original","requested":10}'
    original = replace(original, result=original_result)
    repository = _Repository(original)
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    execute = Mock()
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))

    task = SimpleNamespace(
        name="demo.task",
        request={"delivery_info": {"routing_key": "priority"}, "hostname": "worker-b"},
    )
    tasks.task_prerun_handler(task_id="task-1", task=task)

    assert repository.record == original
    execute.assert_not_called()


def test_legal_retry_claims_a_new_attempt_without_resetting_original_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery retry state is resumable and keeps the first execution timestamp."""

    started_at = timezone.now() - timedelta(minutes=5)
    original = replace(
        _record(status=TaskStatus.RETRY, retries=1, attempt_id="attempt-original"),
        started_at=started_at,
        result='{"error":"transient"}',
    )
    repository = _Repository(original)
    execute = Mock(side_effect=lambda record, **_kwargs: repository.save(record))
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))

    task = SimpleNamespace(
        name="demo.task",
        request={
            "delivery_info": {"routing_key": "priority"},
            "hostname": "worker-b",
            "retries": 1,
        },
    )
    tasks.task_prerun_handler(task_id="task-1", task=task)

    assert repository.record is not None
    assert repository.record.status is TaskStatus.STARTED
    assert repository.record.started_at == started_at
    assert repository.record.retries == 1
    assert repository.record.attempt_id not in {None, "attempt-original"}


def test_stale_duplicate_postrun_cannot_replace_original_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate worker's terminal event must not win the task row."""

    original = _record(attempt_id="attempt-original")
    repository = _Repository(original)
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))
    task = SimpleNamespace(
        name="demo.task",
        request={
            "_task_monitor_attempt_id": "attempt-duplicate",
            "delivery_info": {"routing_key": "priority"},
            "hostname": "worker-b",
        },
    )

    tasks.task_postrun_handler(
        task_id="task-1",
        task=task,
        retval={"outcome": "success", "stored": 99},
        state="SUCCESS",
    )

    assert repository.record == original
    execute.assert_not_called()


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        ("failed", TaskStatus.FAILURE),
        ("partial", TaskStatus.SUCCESS),
        ("blocked", TaskStatus.SUCCESS),
        ("noop", TaskStatus.SUCCESS),
    ],
)
def test_postrun_business_outcome_uses_normalized_contract(
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    expected_status: TaskStatus,
) -> None:
    """Celery success records only normalized business failures as monitor failures."""

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
        retval={"outcome": outcome, "success": False, "stored": 0},
        state="SUCCESS",
    )

    saved = execute.call_args.args[0]
    assert saved.status is expected_status
    assert outcome in saved.result


def test_postrun_projects_required_business_fields_from_oversized_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large audit payloads cannot truncate the final business result."""

    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))
    audit_rows = [
        {"raw_audit_id": f"audit-{index}", "security_code": f"{index:06d}.SZ"}
        for index in range(1_000)
    ]
    retval = {
        "outcome": "partial",
        "success": True,
        "requested": 5_572,
        "succeeded": 5_572,
        "failed": 0,
        "stored": 11_144,
        "phase": "publication",
        "phase_results": [
            {
                "phase": "quote",
                "requested": 5_572,
                "succeeded": 5_572,
                "failed": 0,
                "stored": 5_572,
            },
            {"phase": "publication", "requested": 1, "succeeded": 0, "failed": 1, "stored": 0},
        ],
        "error_code": "MARKET_PUBLICATION_VALIDATION_FAILED",
        "blocked_reason": "MARKET_PUBLICATION_VALIDATION_FAILED",
        "publication_updated": False,
        "publication_run_id": "run-20261005-abc123",
        "raw_audit_references": audit_rows,
        "suspended_codes": [f"{index:06d}.SZ" for index in range(1_000)],
    }

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval=retval,
        state="SUCCESS",
    )

    saved = execute.call_args.args[0]
    assert saved.result is not None
    assert len(saved.result) <= 10_000
    payload = json.loads(saved.result)
    assert payload["outcome"] == "partial"
    assert (payload["requested"], payload["succeeded"], payload["failed"], payload["stored"]) == (
        5_572,
        5_572,
        0,
        11_144,
    )
    assert payload["phase"] == "publication"
    assert payload["phase_results"] == retval["phase_results"]
    assert payload["error_code"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert payload["blocked_reason"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert payload["publication_updated"] is False
    assert payload["publication_run_id"] == "run-20261005-abc123"
    assert "raw_audit_references" not in payload
    assert "suspended_codes" not in payload
    assert "audit-0" not in saved.result
    assert "000000.SZ" not in saved.result
    response = TaskStatusSerializer(task_status_response(saved)).data
    assert response["status"] == TaskStatus.SUCCESS.value
    assert response["outcome"] == "partial"
    assert (
        response["requested"],
        response["succeeded"],
        response["failed"],
        response["stored"],
    ) == (
        5_572,
        5_572,
        0,
        11_144,
    )
    assert response["phase"] == "publication"
    assert [
        (phase["phase"], phase["requested"], phase["succeeded"], phase["failed"], phase["stored"])
        for phase in response["phase_results"]
    ] == [
        (phase["phase"], phase["requested"], phase["succeeded"], phase["failed"], phase["stored"])
        for phase in retval["phase_results"]
    ]
    assert response["error_code"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert response["blocked_reason"] == "MARKET_PUBLICATION_VALIDATION_FAILED"
    assert response["publication_updated"] is False
    assert response["publication_run_id"] == "run-20261005-abc123"


def test_postrun_preserves_small_result_repr_for_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary small task results keep their prior persisted representation."""

    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))
    retval = {"outcome": "success", "stored": 2, "detail": "small result"}

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval=retval,
        state="SUCCESS",
    )

    assert execute.call_args.args[0].result == str(retval)


def test_postrun_preserves_bounded_publication_evidence_from_oversized_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large full-market success results retain publication identities in the API."""

    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))
    publication_ids = (
        "bf8c00f5-59df-42c0-a3cb-44d2e306d668",
        "20d9591d-d4ed-46b4-bb24-f49338e3be3d",
        "82a45361-7c5d-4b22-b303-7fb24488ec1c",
    )
    datasets = [
        {
            "dataset_key": dataset_key,
            "publication_id": publication_id,
            "publication_hash": f"{index:064x}",
            "member_count": 5_572,
            "requested_asset_count": 5_572,
            "covered_asset_count": 5_572,
            "missing_asset_count": 0,
            "policy_identity": "market-policy-v1",
            "as_of": "2026-10-05",
            "published_at": "2026-10-05T09:00:00+08:00",
            "run_id": "market-run-20261005",
            "scope_blocks": [{"asset_code": f"{code:06d}.SZ"} for code in range(1_000)],
        }
        for index, (dataset_key, publication_id) in enumerate(
            zip(
                (
                    "equity.quote.snapshot",
                    "equity.price.bar",
                    "equity.valuation.fact",
                ),
                publication_ids,
                strict=True,
            )
        )
    ]
    retval = {
        "outcome": "success",
        "success": True,
        "requested": 5_572,
        "succeeded": 5_572,
        "failed": 0,
        "stored": 11_144,
        "phase": "publication",
        "phase_results": [
            {
                "phase": "quote",
                "requested": 5_572,
                "succeeded": 5_572,
                "failed": 0,
                "stored": 5_572,
            },
            {"phase": "publication", "requested": 3, "succeeded": 3, "failed": 0, "stored": 3},
        ],
        "publication_updated": True,
        "publication_run_id": "market-run-20261005",
        "publication_ids": list(publication_ids),
        "datasets": datasets,
        "raw_audit_references": [
            {"raw_audit_id": f"raw-audit-{index}", "security_code": f"{index:06d}.SZ"}
            for index in range(1_000)
        ],
        "security_codes": [f"{index:06d}.SZ" for index in range(1_000)],
    }

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval=retval,
        state="SUCCESS",
    )

    saved = execute.call_args.args[0]
    assert saved.result is not None
    assert len(saved.result) <= 10_000
    assert "raw_audit_references" not in saved.result
    assert "scope_blocks" not in saved.result
    assert "security_codes" not in saved.result
    assert "000000.SZ" not in saved.result
    status = task_status_response(saved)
    response = TaskStatusSerializer(status).data
    assert response["outcome"] == "success"
    assert response["publication_updated"] is True
    assert response["publication_run_id"] == "market-run-20261005"
    assert tuple(response["publication_ids"]) == publication_ids
    assert len(response["datasets"]) == 3
    assert {item["dataset_key"]: item["publication_id"] for item in response["datasets"]} == dict(
        zip(
            (
                "equity.quote.snapshot",
                "equity.price.bar",
                "equity.valuation.fact",
            ),
            publication_ids,
            strict=True,
        )
    )
    assert all(item["publication_hash"] for item in response["datasets"])
    assert all(item["member_count"] == 5_572 for item in response["datasets"])
    assert all(item["policy_identity"] == "market-policy-v1" for item in response["datasets"])
    assert all(item["policy_version"] == "market-policy-v1" for item in response["datasets"])
    assert all(item["as_of"] == "2026-10-05" for item in response["datasets"])
    assert all(item["run_id"] == "market-run-20261005" for item in response["datasets"])


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


def test_postrun_technical_failure_overrides_nonfailed_business_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Celery failure remains authoritative even when the payload is partial."""

    repository = _Repository(_record())
    execute = Mock()
    monkeypatch.setattr(tasks, "get_repository", lambda: repository)
    monkeypatch.setattr(tasks, "get_use_case", lambda: SimpleNamespace(execute=execute))

    tasks.task_postrun_handler(
        task_id="task-1",
        task=SimpleNamespace(name="demo.task"),
        retval={"outcome": "partial", "success": True, "stored": 1},
        state="FAILURE",
    )

    assert execute.call_args.args[0].status is TaskStatus.FAILURE


def test_task_signal_lifecycle_records_start_retry_failure_and_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    execute = Mock(side_effect=lambda record, **_kwargs: repository.save(record))
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
    first_attempt_id = repository.record.attempt_id
    assert first_attempt_id is not None

    tasks.task_retry_handler(
        task_id="task-1",
        reason="temporary",
        einfo=SimpleNamespace(traceback="retry trace"),
    )
    assert repository.record.status is TaskStatus.RETRY
    assert repository.record.retries == 1

    # Celery may reuse a task object/request during retry; the retry must not
    # inherit the prior Task Monitor attempt marker.
    tasks.task_prerun_handler(
        task_id="task-1",
        task=celery_task,
        args=(1,),
        kwargs={"mode": "safe"},
    )
    assert repository.record.status is TaskStatus.STARTED
    assert repository.record.attempt_id is not None
    assert repository.record.attempt_id != first_attempt_id
    assert celery_task.request["_task_monitor_attempt_id"] == repository.record.attempt_id

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
