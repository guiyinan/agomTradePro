"""Application dependency providers for task monitor interfaces."""

from __future__ import annotations

from core.celery import app as celery_app


def get_task_record_repository():
    """Return the default task record repository."""

    from apps.task_monitor.infrastructure.providers import DjangoTaskRecordRepository

    return DjangoTaskRecordRepository()


def get_celery_health_checker():
    """Return the default Celery health checker."""

    from apps.task_monitor.infrastructure.providers import CeleryHealthChecker

    return CeleryHealthChecker(celery_app=celery_app)
