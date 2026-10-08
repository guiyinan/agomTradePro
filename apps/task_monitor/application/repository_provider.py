"""Composition helpers for task_monitor application consumers."""

from __future__ import annotations

from typing import Any

from apps.task_monitor.domain.interfaces import TaskOrphanEvidenceProviderProtocol
from core.celery import app as celery_app
from core.integration.task_lease_probe_registry import get_domain_task_lease_probes


def get_task_record_repository() -> Any:
    """Return the default task record repository."""

    from apps.task_monitor.infrastructure.providers import DjangoTaskRecordRepository

    return DjangoTaskRecordRepository()


def get_celery_health_checker() -> Any:
    """Return the default Celery health checker."""

    from apps.task_monitor.infrastructure.providers import CeleryHealthChecker

    return CeleryHealthChecker(celery_app=celery_app)


def get_task_orphan_evidence_provider() -> TaskOrphanEvidenceProviderProtocol:
    """Return the read-only Celery evidence provider for maintenance reconciliation."""

    from apps.task_monitor.infrastructure.orphan_evidence import CeleryTaskOrphanEvidenceProvider

    return CeleryTaskOrphanEvidenceProvider(
        celery_app=celery_app,
        domain_lease_probes=get_domain_task_lease_probes(),
    )


def get_database_backup_service() -> Any:
    """Return the default database backup service."""

    from apps.task_monitor.infrastructure.backup_service import DatabaseBackupService

    return DatabaseBackupService()


def get_operational_alert_repository() -> Any:
    """Return the operational alert persistence adapter."""

    from apps.task_monitor.infrastructure.operational_alert_repository import (
        DjangoOperationalAlertRepository,
    )

    return DjangoOperationalAlertRepository()


def get_maintenance_status_reader() -> Any:
    """Return the read-only maintenance evidence adapter."""

    from apps.task_monitor.infrastructure.maintenance_status import (
        DjangoMaintenanceStatusReader,
    )

    return DjangoMaintenanceStatusReader()


def get_scheduler_repository() -> Any:
    """Return the default periodic task catalog repository."""

    from apps.task_monitor.infrastructure.providers import DjangoSchedulerRepository

    return DjangoSchedulerRepository()


def get_scheduler_bootstrap_gateway() -> Any:
    """Return the default scheduler bootstrap gateway."""

    from apps.task_monitor.infrastructure.providers import (
        ManagementCommandSchedulerBootstrapGateway,
    )

    return ManagementCommandSchedulerBootstrapGateway()


def get_scheduler_configuration_gateway() -> Any:
    """Return the default scheduler configuration gateway."""

    from apps.task_monitor.infrastructure.providers import (
        ManagementCommandSchedulerConfigurationGateway,
    )

    return ManagementCommandSchedulerConfigurationGateway()
