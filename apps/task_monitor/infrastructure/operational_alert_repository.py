"""Persistence adapter for aggregated operational alerts."""

from __future__ import annotations

from typing import Any

from apps.task_monitor.infrastructure.models import TaskAlertModel


class DjangoOperationalAlertRepository:
    """Persist non-exception operational alerts for scheduler visibility."""

    def record(
        self,
        *,
        level: str,
        task_name: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        task_id: str = "",
    ) -> str:
        alert = TaskAlertModel.objects.create(
            level=level,
            task_id=task_id or "operational",
            task_name=task_name,
            title=title,
            message=message,
            metadata=metadata or {},
        )
        return str(alert.pk)
