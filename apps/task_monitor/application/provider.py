"""Application dependency providers for task monitor interfaces."""

from __future__ import annotations

from apps.task_monitor.application.repository_provider import (
    get_celery_health_checker,
    get_task_record_repository,
)
