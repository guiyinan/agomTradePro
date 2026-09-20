"""Application-level task-monitor query helpers for TUI/runtime consumers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.task_monitor.application.provider import get_task_record_repository
from apps.task_monitor.domain.entities import TaskExecutionRecord
from apps.task_monitor.domain.interfaces import TaskRecordRepositoryProtocol


def list_task_executions(
    task_names: tuple[str, ...], *, limit: int = 100
) -> list[TaskExecutionRecord]:
    """Return recent task evidence, newest first, through the repository contract."""
    repository = cast(TaskRecordRepositoryProtocol, get_task_record_repository())
    records = [
        record for name in task_names for record in repository.list_by_task_name(name, limit=limit)
    ]
    return sorted(
        records,
        key=lambda record: record.finished_at
        or record.started_at
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


def has_recent_task_failures(*, limit: int = 1) -> bool:
    """Return whether the default task-list view can surface selectable task rows."""

    repository = get_task_record_repository()
    return bool(repository.list_recent_failures(limit=limit))
