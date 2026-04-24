"""Django model discovery shim for Task Monitor.

The concrete ORM models live under infrastructure to keep the module layering
consistent, while Django discovers app models through apps.task_monitor.models.
"""

from apps.task_monitor.infrastructure.models import TaskAlertModel, TaskExecutionModel

__all__ = ["TaskExecutionModel", "TaskAlertModel"]
