"""Application facade for recording aggregated operational alerts."""

from __future__ import annotations

import logging
from typing import Any

from apps.task_monitor.application.repository_provider import (
    get_operational_alert_repository,
)

logger = logging.getLogger(__name__)


def record_operational_alert(
    *,
    level: str,
    task_name: str,
    title: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    task_id: str = "",
) -> str:
    """Record one aggregated alert without exposing ORM details to callers."""

    try:
        return get_operational_alert_repository().record(
            level=level,
            task_name=task_name,
            title=title,
            message=message,
            metadata=metadata,
            task_id=task_id,
        )
    except Exception:
        logger.exception("Failed to persist operational alert for %s", task_name)
        return ""
