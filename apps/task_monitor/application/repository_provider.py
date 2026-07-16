"""Composition helpers for task_monitor application consumers."""

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


def get_database_backup_service():
    """Return the default database backup service."""

    from apps.task_monitor.infrastructure.backup_service import DatabaseBackupService

    return DatabaseBackupService()


def get_operational_alert_repository():
    """Return the operational alert persistence adapter."""

    from apps.task_monitor.infrastructure.operational_alert_repository import (
        DjangoOperationalAlertRepository,
    )

    return DjangoOperationalAlertRepository()


def get_maintenance_status_reader():
    """Return the read-only maintenance evidence adapter."""

    from apps.task_monitor.infrastructure.maintenance_status import (
        DjangoMaintenanceStatusReader,
    )

    return DjangoMaintenanceStatusReader()


def get_scheduler_repository():
    """Return the default periodic task catalog repository."""

    from apps.task_monitor.infrastructure.providers import DjangoSchedulerRepository

    return DjangoSchedulerRepository()


def get_scheduler_bootstrap_gateway():
    """Return the default scheduler bootstrap gateway."""

    from apps.task_monitor.infrastructure.providers import (
        ManagementCommandSchedulerBootstrapGateway,
    )

    return ManagementCommandSchedulerBootstrapGateway()


def get_scheduler_configuration_gateway():
    """Return the default scheduler configuration gateway."""

    from apps.task_monitor.infrastructure.providers import (
        ManagementCommandSchedulerConfigurationGateway,
    )

    return ManagementCommandSchedulerConfigurationGateway()
