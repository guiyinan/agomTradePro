"""Application-level task-monitor query helpers for TUI/runtime consumers."""

from __future__ import annotations

from apps.task_monitor.application.provider import get_task_record_repository


def has_recent_task_failures(*, limit: int = 1) -> bool:
    """Return whether the default task-list view can surface selectable task rows."""

    repository = get_task_record_repository()
    return bool(repository.list_recent_failures(limit=limit))
