"""Template-oriented services for the task monitor pages."""

from __future__ import annotations

from apps.task_monitor.application.repository_provider import (
    get_celery_health_checker,
    get_scheduler_bootstrap_gateway,
    get_scheduler_configuration_gateway,
    get_scheduler_repository,
    get_task_record_repository,
)
from apps.task_monitor.application.readiness_monitor_service import (
    get_personal_readiness_monitor_placeholder,
    get_personal_readiness_monitor_summary,
)
from apps.task_monitor.application.use_cases import (
    BootstrapDefaultSchedulesUseCase,
    ConfigureReadinessScheduleUseCase,
    GetReadinessScheduleUseCase,
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
        "readiness_schedule": GetReadinessScheduleUseCase(
            scheduler_repository=get_scheduler_repository(),
        ).execute(),
        "readiness_monitor": get_personal_readiness_monitor_placeholder(),
        "periodic_task_admin_url": "/admin/django_celery_beat/periodictask/",
        "crontab_admin_url": "/admin/django_celery_beat/crontabschedule/",
        "task_execution_admin_url": "/admin/task_monitor/taskexecutionmodel/",
    }


def get_readiness_monitor_context(*, strict_runtime: bool = False) -> dict:
    """Return the daily readiness monitor payload for page JSON refreshes."""

    return get_personal_readiness_monitor_summary(strict_runtime=strict_runtime)


def bootstrap_scheduler_defaults() -> dict:
    """Initialize default scheduler tasks and return a UI-friendly payload."""

    response = BootstrapDefaultSchedulesUseCase(
        gateway=get_scheduler_bootstrap_gateway(),
    ).execute()
    return {
        "executed_commands": response.executed_commands,
        "output_lines": response.output_lines,
    }


def configure_readiness_schedule(
    *,
    quote_pre_refresh_time: str,
    daily_evidence_time: str,
    weekly_auto_advisor_time: str,
) -> dict:
    """Configure post-close readiness schedule times from the console page."""

    response = ConfigureReadinessScheduleUseCase(
        gateway=get_scheduler_configuration_gateway(),
    ).execute(
        quote_pre_refresh_time=quote_pre_refresh_time,
        daily_evidence_time=daily_evidence_time,
        weekly_auto_advisor_time=weekly_auto_advisor_time,
    )
    return {
        "executed_commands": response.executed_commands,
        "output_lines": response.output_lines,
        "quote_pre_refresh_time": response.quote_pre_refresh_time,
        "daily_evidence_time": response.daily_evidence_time,
        "weekly_auto_advisor_time": response.weekly_auto_advisor_time,
    }
