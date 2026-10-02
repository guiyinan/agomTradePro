"""Fail-closed contract tests for the active Celery/Task Monitor attempt identity."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.task_monitor.application.current_task_attempt_identity import (
    CurrentTaskAttemptIdentity,
    CurrentTaskAttemptIdentityUnavailable,
    get_current_task_attempt_identity,
)
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus
from core.integration.task_monitor_runtime import (
    CurrentTaskAttemptIdentity as FacadeTaskAttemptIdentity,
)
from core.integration.task_monitor_runtime import (
    get_current_task_attempt_identity as facade_get_current_task_attempt_identity,
)


def _record(
    *,
    task_id: str = "celery-task-1",
    attempt_id: str | None = "attempt-1",
    status: TaskStatus = TaskStatus.STARTED,
) -> TaskExecutionRecord:
    """Build one Task Monitor record for identity verification tests."""

    return TaskExecutionRecord(
        task_id=task_id,
        task_name="demo.task",
        status=status,
        args=(),
        kwargs={},
        started_at=timezone.now(),
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="default",
        worker="worker-1",
        attempt_id=attempt_id,
    )


def _request(*, task_id: object = "celery-task-1", attempt_id: object = "attempt-1") -> object:
    """Build the current Celery request shape consumed by the getter."""

    return SimpleNamespace(id=task_id, _task_monitor_attempt_id=attempt_id)


def _patch_identity_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    request: object,
    record: TaskExecutionRecord | None,
    repository_error: Exception | None = None,
) -> Mock:
    """Inject an active request and a read-only Task Monitor repository stub."""

    repository = Mock()
    if repository_error is not None:
        repository.get_by_task_id.side_effect = repository_error
    else:
        repository.get_by_task_id.return_value = record
    monkeypatch.setattr(
        "apps.task_monitor.application.current_task_attempt_identity.current_task",
        SimpleNamespace(request=request),
    )
    monkeypatch.setattr(
        "apps.task_monitor.application.current_task_attempt_identity.get_task_record_repository",
        lambda: repository,
    )
    return repository


def test_current_task_attempt_identity_requires_matching_started_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _patch_identity_context(
        monkeypatch,
        request=_request(),
        record=_record(),
    )

    identity = get_current_task_attempt_identity()

    assert identity == CurrentTaskAttemptIdentity(
        task_id="celery-task-1",
        attempt_id="attempt-1",
    )
    repository.get_by_task_id.assert_called_once_with("celery-task-1")


@pytest.mark.parametrize(
    ("celery_request", "record", "repository_error"),
    [
        (None, _record(), None),
        (_request(task_id=None), _record(), None),
        (_request(attempt_id=None), _record(), None),
        (_request(task_id=" bad"), _record(), None),
        (_request(attempt_id="x" * 161), _record(), None),
        (_request(), None, None),
        (_request(), _record(status=TaskStatus.RETRY), None),
        (_request(), _record(status=TaskStatus.SUCCESS), None),
        (_request(), _record(attempt_id="attempt-old"), None),
        (_request(), _record(task_id="other-task"), None),
        (_request(), None, RuntimeError("database unavailable")),
    ],
)
def test_current_task_attempt_identity_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    celery_request: object,
    record: TaskExecutionRecord | None,
    repository_error: Exception | None,
) -> None:
    _patch_identity_context(
        monkeypatch,
        request=celery_request,
        record=record,
        repository_error=repository_error,
    )

    with pytest.raises(CurrentTaskAttemptIdentityUnavailable) as captured:
        get_current_task_attempt_identity()

    assert captured.value.code == "CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"


def test_retry_and_duplicate_request_markers_cannot_claim_another_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited retry marker or duplicate-delivery marker cannot pass as current."""

    for request_attempt_id, stored_attempt_id, status in (
        ("attempt-1", "attempt-1", TaskStatus.RETRY),
        ("duplicate-attempt", "attempt-1", TaskStatus.STARTED),
    ):
        _patch_identity_context(
            monkeypatch,
            request=_request(attempt_id=request_attempt_id),
            record=_record(attempt_id=stored_attempt_id, status=status),
        )

        with pytest.raises(CurrentTaskAttemptIdentityUnavailable) as captured:
            get_current_task_attempt_identity()

        assert captured.value.code == "CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"


def test_integration_facade_exports_typed_identity_getter() -> None:
    assert facade_get_current_task_attempt_identity is get_current_task_attempt_identity
    assert FacadeTaskAttemptIdentity is CurrentTaskAttemptIdentity


@pytest.mark.parametrize(
    "value",
    ["", " leading", "trailing ", "line\nbreak", "雪", "x" * 256],
)
def test_identity_contract_rejects_noncanonical_or_oversized_task_id(value: str) -> None:
    with pytest.raises(CurrentTaskAttemptIdentityUnavailable):
        CurrentTaskAttemptIdentity(task_id=value, attempt_id="attempt-1")


@pytest.mark.parametrize("value", ["", "space value", "λ", "x" * 161])
def test_identity_contract_rejects_noncanonical_or_oversized_attempt_id(value: str) -> None:
    with pytest.raises(CurrentTaskAttemptIdentityUnavailable):
        CurrentTaskAttemptIdentity(task_id="celery-task-1", attempt_id=value)
