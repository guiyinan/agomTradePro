"""Celery entrypoint for the fail-closed decision-readiness guard."""

from __future__ import annotations

from typing import Any

from celery import shared_task

from .decision_readiness_guard import AUDIT_TASK_NAME, run_decision_readiness_guard


@shared_task(  # type: ignore[misc]
    name=AUDIT_TASK_NAME,
    time_limit=120,
    soft_time_limit=105,
)
def audit_decision_readiness_task() -> dict[str, Any]:
    """Run the scheduled audit and fail closed on unreliable decision data."""

    return run_decision_readiness_guard()


__all__ = ["audit_decision_readiness_task"]
