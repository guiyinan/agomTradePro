"""Composition-root facade for Task Monitor reads and progress writes."""

from apps.task_monitor.application.current_task_attempt_identity import (
    CurrentTaskAttemptIdentity,
    CurrentTaskAttemptIdentityUnavailable,
    get_current_task_attempt_identity,
)
from apps.task_monitor.application.dtos import (
    TaskBusinessProjection,
    project_task_business_result,
)
from apps.task_monitor.application.query_services import list_task_executions
from apps.task_monitor.application.tracking import (
    TaskProgress,
    TaskProgressPhase,
    record_current_task_progress,
)
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskStatus

__all__ = [
    "TaskBusinessProjection",
    "CurrentTaskAttemptIdentity",
    "CurrentTaskAttemptIdentityUnavailable",
    "TaskExecutionRecord",
    "TaskProgress",
    "TaskProgressPhase",
    "TaskStatus",
    "list_task_executions",
    "get_current_task_attempt_identity",
    "project_task_business_result",
    "record_current_task_progress",
]
