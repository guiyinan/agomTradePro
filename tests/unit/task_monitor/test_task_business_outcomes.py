"""Task Monitor must distinguish Celery completion from business success."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

from apps.task_monitor.application.tasks import task_postrun_handler
from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskPriority,
    TaskStatus,
)


def _started_record() -> TaskExecutionRecord:
    """Build an existing task record as seen by the post-run signal."""

    return TaskExecutionRecord(
        task_id="task-1",
        task_name="tests.business_task",
        status=TaskStatus.STARTED,
        args=(),
        kwargs={},
        started_at=timezone.now() - timedelta(seconds=2),
        finished_at=None,
        result=None,
        exception=None,
        traceback=None,
        runtime_seconds=None,
        retries=0,
        priority=TaskPriority.NORMAL,
        queue="celery",
        worker="worker-1",
    )


def test_postrun_records_failed_business_payload_as_failure() -> None:
    """A Celery SUCCESS state cannot overwrite an explicit business failure."""

    repository = MagicMock()
    repository.get_by_task_id.return_value = _started_record()
    use_case = MagicMock()
    task = MagicMock()
    task.name = "tests.business_task"

    with (
        patch(
            "apps.task_monitor.application.tasks.get_repository",
            return_value=repository,
        ),
        patch(
            "apps.task_monitor.application.tasks.get_use_case",
            return_value=use_case,
        ),
    ):
        task_postrun_handler(
            task_id="task-1",
            task=task,
            retval={
                "success": False,
                "outcome": "failed",
                "stage": "sync",
                "error": "all providers failed",
            },
            state="SUCCESS",
        )

    saved_record = use_case.execute.call_args.args[0]
    assert saved_record.status is TaskStatus.FAILURE
    assert saved_record.exception == "[sync] all providers failed"
