"""Template-oriented services for the task monitor pages."""

from __future__ import annotations

from apps.task_monitor.application.repository_provider import (
    get_celery_health_checker,
    get_scheduler_bootstrap_gateway,
    get_scheduler_repository,
    get_task_record_repository,
)
from apps.task_monitor.application.use_cases import (
    BootstrapDefaultSchedulesUseCase,
    GetSchedulerConsoleUseCase,
)


def get_scheduler_console_context(*, limit: int = 100) -> dict:
    """Return template context for the scheduler console page."""

    response = GetSchedulerConsoleUseCase(
        scheduler_repository=get_scheduler_repository(),
        health_checker=get_celery_health_checker(),
        task_record_repository=get_task_record_repository(),
    ).execute(limit=limit)

    return {
        "page_title": "计划任务中心",
        "summary": response.summary,
        "health": response.health,
        "periodic_tasks": response.periodic_tasks,
        "recent_failures": response.recent_failures,
        "periodic_task_admin_url": "/admin/django_celery_beat/periodictask/",
        "crontab_admin_url": "/admin/django_celery_beat/crontabschedule/",
        "task_execution_admin_url": "/admin/task_monitor/taskexecutionmodel/",
    }


def bootstrap_scheduler_defaults() -> dict:
    """Initialize default scheduler tasks and return a UI-friendly payload."""

    response = BootstrapDefaultSchedulesUseCase(
        gateway=get_scheduler_bootstrap_gateway(),
    ).execute()
    return {
        "executed_commands": response.executed_commands,
        "output_lines": response.output_lines,
    }
