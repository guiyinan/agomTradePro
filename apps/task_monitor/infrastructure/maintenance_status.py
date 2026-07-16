"""Read-only maintenance status adapter for the Task Monitor console."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, cast

from django.conf import settings  # type: ignore[import-untyped]
from django_celery_beat.models import PeriodicTask  # type: ignore[import-untyped]

from apps.task_monitor.infrastructure.models import TaskExecutionModel


class DjangoMaintenanceStatusReader:
    """Collect backup, cleanup, database-size, and schedule evidence."""

    BACKUP_TASK = "apps.task_monitor.application.tasks.backup_database_task"
    CLEANUP_TASK = "apps.task_monitor.application.tasks.cleanup_old_task_records"

    def read(self) -> dict[str, Any]:
        """Return maintenance evidence without exposing ORM objects."""

        backup = self._latest_execution(self.BACKUP_TASK)
        cleanup = self._latest_execution(self.CLEANUP_TASK)
        db_name = settings.DATABASES["default"].get("NAME")
        db_path = Path(str(db_name)) if db_name else None
        database_size = db_path.stat().st_size if db_path and db_path.is_file() else None
        return {
            "latest_backup_at": backup.finished_at if backup else None,
            "latest_backup_status": backup.status if backup else "never",
            "latest_cleanup_at": cleanup.finished_at if cleanup else None,
            "latest_cleanup_count": self._deleted_count(cleanup.result if cleanup else None),
            "database_size_bytes": database_size,
            "database_size_mb": round(database_size / 1024 / 1024, 1) if database_size else None,
            "backup_next_run_at": self._next_run(self.BACKUP_TASK),
            "cleanup_next_run_at": self._next_run(self.CLEANUP_TASK),
        }

    @staticmethod
    def _latest_execution(task_name: str) -> TaskExecutionModel | None:
        return cast(
            TaskExecutionModel | None,
            TaskExecutionModel._default_manager.filter(task_name=task_name)
            .order_by("-created_at")
            .first(),
        )

    @staticmethod
    def _deleted_count(result: Any) -> int:
        return int(result.get("deleted_count", 0)) if isinstance(result, dict) else 0

    @staticmethod
    def _next_run(task_name: str) -> datetime | None:
        from django.utils import timezone  # type: ignore[import-untyped]

        task = PeriodicTask._default_manager.filter(task=task_name, enabled=True).first()
        if task is None:
            return None
        # django-celery-beat exposes the next occurrence through the schedule.
        reference = task.last_run_at
        if reference is None:
            reference = timezone.now()
        return cast(datetime, timezone.now() + task.schedule.remaining_estimate(reference))
