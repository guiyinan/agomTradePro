"""Composition-root facade for Task Monitor reads used by other apps."""

from apps.task_monitor.application.dtos import (
    TaskBusinessProjection,
    project_task_business_result,
)
from apps.task_monitor.application.query_services import list_task_executions
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskStatus

__all__ = [
    "TaskBusinessProjection",
    "TaskExecutionRecord",
    "TaskStatus",
    "list_task_executions",
    "project_task_business_result",
]
