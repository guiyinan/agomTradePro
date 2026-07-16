"""Technical registry for persisting cross-application operational alerts."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)
OperationalAlertHandler = Callable[..., str]

_handler: OperationalAlertHandler | None = None
_lock = RLock()


def register_operational_alert_handler(handler: OperationalAlertHandler) -> None:
    """Register the composition-root handler for operational alerts."""

    global _handler
    with _lock:
        _handler = handler


def record_operational_alert(
    *,
    level: str,
    task_name: str,
    title: str,
    message: str,
    metadata: dict[str, Any] | None = None,
    task_id: str = "",
) -> str:
    """Dispatch an alert without creating an app-to-app import dependency."""

    with _lock:
        handler = _handler
    if handler is None:
        logger.warning("Operational alert handler is unavailable: %s", title)
        return ""
    return handler(
        level=level,
        task_name=task_name,
        title=title,
        message=message,
        metadata=metadata,
        task_id=task_id,
    )
