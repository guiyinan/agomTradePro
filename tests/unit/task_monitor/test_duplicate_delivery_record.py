"""Task Monitor evidence must survive duplicate Celery deliveries."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus
from apps.task_monitor.infrastructure.models import TaskExecutionModel
from apps.task_monitor.infrastructure.repositories import DjangoTaskRecordRepository


@pytest.mark.django_db
def test_duplicate_started_record_preserves_original_start_and_live_progress() -> None:
    """A visibility redelivery cannot reset the original execution evidence."""

    original_started_at = timezone.now() - timedelta(seconds=30)
    original = TaskExecutionRecord(
        task_id="duplicate-delivery-task",
        task_name="demo.task",
        status=TaskStatus.STARTED,
        args=(),
        kwargs={},
        started_at=original_started_at,
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="default",
        worker="worker-1",
    )
    repository = DjangoTaskRecordRepository()
    repository.save(original)
    assert repository.update_result_if_status(
        task_id=original.task_id,
        result='{"phase":"quote","succeeded":10}',
        expected_status=TaskStatus.STARTED,
    )

    duplicate = TaskExecutionRecord(
        task_id=original.task_id,
        task_name=original.task_name,
        status=TaskStatus.STARTED,
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
        worker="worker-duplicate",
    )
    repository.save(duplicate)

    current = repository.get_by_task_id(original.task_id)
    assert current is not None
    assert current.started_at == original_started_at
    assert current.result == '{"phase":"quote","succeeded":10}'
    assert current.worker == "worker-1"


@pytest.mark.django_db
def test_retry_claims_new_attempt_when_retry_signal_was_not_persisted() -> None:
    """A higher Celery retry ordinal can recover from a missed RETRY signal."""

    repository = DjangoTaskRecordRepository()
    original = TaskExecutionRecord(
        task_id="retry-without-signal",
        task_name="demo.task",
        status=TaskStatus.STARTED,
        args=(),
        kwargs={},
        started_at=timezone.now() - timedelta(seconds=30),
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="default",
        worker="worker-1",
        attempt_id="attempt-original",
    )
    repository.save(original)

    repository.save(
        replace(
            original,
            retries=1,
            attempt_id="attempt-retry",
            worker="worker-2",
        )
    )

    row = TaskExecutionModel.objects.get(task_id=original.task_id)
    assert row.status == TaskStatus.STARTED.value
    assert row.attempt_id == "attempt-retry"
    assert row.retries == 1
    assert row.started_at == original.started_at
