"""task_monitor runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_task_monitor_statistics(
    task_name: str | None = None,
    days: int = 7,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    if not task_name:
        return {
            "success": False,
            "error": "task_name is required",
        }
    return client.task_monitor.statistics(task_name=task_name, days=days)


def _fallback_get_task_monitor_status(task_id: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    try:
        return client.task_monitor.get_task_status(task_id)
    except Exception as exc:
        return {
            "success": False,
            "task_id": task_id,
            "error": str(exc),
        }


def _fallback_list_task_monitor_tasks() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.task_monitor.list_tasks()


def _fallback_get_task_monitor_dashboard() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.task_monitor.dashboard()


def _fallback_get_task_monitor_celery_health() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.task_monitor.celery_health()


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_task_monitor_statistics": _fallback_get_task_monitor_statistics,
    "get_task_monitor_status": _fallback_get_task_monitor_status,
    "list_task_monitor_tasks": _fallback_list_task_monitor_tasks,
    "get_task_monitor_dashboard": _fallback_get_task_monitor_dashboard,
    "get_task_monitor_celery_health": _fallback_get_task_monitor_celery_health,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
