"""Framework-neutral business outcome helpers for background tasks."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class TaskBusinessOutcome(str, Enum):
    """Normalized business outcomes carried by serialized task payloads."""

    SUCCESS = "success"
    PARTIAL = "partial"
    NOOP = "noop"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"


def resolve_task_business_outcome(result: object) -> TaskBusinessOutcome:
    """Resolve a task's business outcome without relying on Celery state alone."""

    if not isinstance(result, Mapping):
        return TaskBusinessOutcome.UNKNOWN

    success = result.get("success")
    if success is False:
        return TaskBusinessOutcome.FAILED

    raw_outcome = result.get("outcome")
    if isinstance(raw_outcome, str):
        try:
            return TaskBusinessOutcome(raw_outcome.strip().lower())
        except ValueError:
            return TaskBusinessOutcome.UNKNOWN

    if result.get("partial_success") is True:
        return TaskBusinessOutcome.PARTIAL
    if result.get("stage") == "gate_blocked":
        return TaskBusinessOutcome.BLOCKED
    if success is True:
        return TaskBusinessOutcome.SUCCESS
    return TaskBusinessOutcome.UNKNOWN


def task_business_failure_message(result: object) -> str | None:
    """Extract a compact failure description from a serialized task payload."""

    if resolve_task_business_outcome(result) is not TaskBusinessOutcome.FAILED:
        return None
    if not isinstance(result, Mapping):
        return "Task returned a failed business outcome"

    error = result.get("error")
    stage = result.get("stage")
    message = str(error).strip() if error is not None else "Task returned a failed business outcome"
    if isinstance(stage, str) and stage.strip():
        return f"[{stage.strip()}] {message}"
    return message
