"""Shared normalized business-outcome helpers for Alpha Celery tasks."""

from __future__ import annotations

from typing import Any


def task_outcome_fields(
    outcome: str,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
) -> dict[str, object]:
    """Build the normalized task-monitor projection for one business result."""

    return {
        "outcome": outcome,
        "success": outcome in {"success", "partial", "noop"},
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
    }


def completed_task_result(
    payload: dict[str, Any],
    *,
    requested: int = 1,
    stored: int = 1,
) -> dict[str, Any]:
    """Attach a successful business outcome to an authoritative task payload."""

    return {
        **payload,
        **task_outcome_fields("success", requested, requested, 0, stored),
    }


def failed_task_result(*, reason: str, requested: int = 1) -> dict[str, Any]:
    """Return a stable failure without publishing dynamic exception details."""

    return {
        "status": "error",
        "reason": reason,
        **task_outcome_fields("failed", requested, 0, requested, 0),
    }


def daily_inference_outcome(
    *,
    refresh_data: bool,
    refresh_status: object,
    queue_succeeded: bool,
) -> dict[str, object]:
    """Summarize the optional refresh and mandatory prediction-queue stages."""

    requested = 2 if refresh_data else 1
    refresh_succeeded = not refresh_data or refresh_status == "success"
    succeeded = int(queue_succeeded) + int(refresh_data and refresh_succeeded)
    failed = requested - succeeded
    if failed == 0:
        outcome = "success"
    elif succeeded:
        outcome = "partial"
    else:
        outcome = "failed"
    return task_outcome_fields(outcome, requested, succeeded, failed, 0)


def scoped_work_outcome(
    *,
    requested: int,
    failed: int,
    stored: int,
    no_work: bool,
) -> dict[str, object]:
    """Summarize isolated scope work while preserving partial failures."""

    succeeded = max(requested - failed, 0)
    if requested == 0 or (no_work and failed == 0):
        outcome = "noop"
    elif failed == requested:
        outcome = "failed"
    elif failed:
        outcome = "partial"
    else:
        outcome = "success"
    return task_outcome_fields(outcome, requested, succeeded, failed, stored)


def refresh_summary_outcome(
    *,
    status: str,
    requested: int,
    failed: int = 0,
    stored: int = 0,
    no_work: bool = False,
) -> dict[str, object]:
    """Map an authoritative refresh summary into the task outcome vocabulary."""

    if status == "success":
        return scoped_work_outcome(
            requested=requested,
            failed=failed,
            stored=stored,
            no_work=no_work,
        )
    if status in {"blocked", "skipped"}:
        outcome = "noop" if requested == 0 else "blocked"
        return task_outcome_fields(outcome, requested, 0, 0, 0)
    failed_count = max(requested, 1)
    return task_outcome_fields("failed", failed_count, 0, failed_count, 0)


__all__ = [
    "completed_task_result",
    "daily_inference_outcome",
    "failed_task_result",
    "refresh_summary_outcome",
    "scoped_work_outcome",
    "task_outcome_fields",
]
