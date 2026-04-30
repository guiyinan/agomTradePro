"""Helpers for persisting queued tasks before Celery worker pickup."""

from __future__ import annotations

from typing import Any

from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus


def record_pending_task(
    *,
    task_id: str,
    task_name: str,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> None:
    """Persist one queued task so UI/API layers can see it before worker pickup."""
    RecordTaskExecutionUseCase(repository=get_task_record_repository()).execute(
        TaskExecutionRecord(
            task_id=task_id,
            task_name=task_name,
            status=TaskStatus.PENDING,
            args=args,
            kwargs=kwargs or {},
            started_at=None,
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue=None,
            worker=None,
        )
    )
