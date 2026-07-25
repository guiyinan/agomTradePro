"""Application dependency providers for task monitor interfaces."""

from __future__ import annotations

from apps.task_monitor.application.repository_provider import (
    get_celery_health_checker as get_celery_health_checker,
)
from apps.task_monitor.application.repository_provider import (
    get_scheduler_bootstrap_gateway as get_scheduler_bootstrap_gateway,
)
from apps.task_monitor.application.repository_provider import (
    get_scheduler_repository as get_scheduler_repository,
)
from apps.task_monitor.application.repository_provider import (
    get_task_record_repository as get_task_record_repository,
)
