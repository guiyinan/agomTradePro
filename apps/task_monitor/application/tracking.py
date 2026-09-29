"""Helpers for persisting queued tasks before Celery worker pickup."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from celery import current_task

from apps.task_monitor.application.repository_provider import get_task_record_repository
from apps.task_monitor.application.use_cases import RecordTaskExecutionUseCase
from apps.task_monitor.domain.entities import TaskExecutionRecord, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)
_SAFE_PROGRESS_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class TaskProgressPhase:
    """Safe counters for a completed or currently running phase."""

    phase: str
    requested: int | None = None
    succeeded: int | None = None
    failed: int | None = None
    stored: int | None = None
    count_unit: str | None = None
    stored_count_unit: str | None = None


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """A bounded, diagnostic-free snapshot for one active Celery task."""

    phase: str
    requested: int | None = None
    succeeded: int | None = None
    failed: int | None = None
    stored: int | None = None
    count_unit: str | None = None
    stored_count_unit: str | None = None
    phase_results: tuple[TaskProgressPhase, ...] = ()


def record_task_progress(*, task_id: str, progress: TaskProgress) -> bool:
    """Persist safe progress only while the Task Monitor record is STARTED.

    Progress is stored in the existing result column and is replaced by the
    authoritative business result when Celery emits task_postrun. Missing
    records, terminal records, and monitor persistence errors never alter task
    business execution.
    """

    try:
        payload = _progress_payload(progress)
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 255:
            return False
        repository = get_task_record_repository()
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return (
            repository.update_result_if_status(
                task_id=task_id,
                result=serialized,
                expected_status=TaskStatus.STARTED,
            )
            is True
        )
    except Exception as exc:
        logger.info("Task progress persistence failed: error_type=%s", type(exc).__name__)
        return False


def record_current_task_progress(progress: TaskProgress) -> bool:
    """Persist progress for the active Celery task, if Task Monitor tracks it."""

    try:
        request = getattr(current_task, "request", None)
        task_id = getattr(request, "id", None)
        if not isinstance(task_id, str) or not task_id:
            return False
        attempt_id = getattr(request, "_task_monitor_attempt_id", None)
        if not isinstance(attempt_id, str) or not attempt_id:
            return record_task_progress(task_id=task_id, progress=progress)
        repository = get_task_record_repository()
        payload = _progress_payload(progress)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return (
            repository.update_result_if_status(
                task_id=task_id,
                result=serialized,
                expected_status=TaskStatus.STARTED,
                expected_attempt_id=attempt_id,
            )
            is True
        )
    except Exception as exc:
        logger.info("Current task progress unavailable: error_type=%s", type(exc).__name__)
        return False


def _progress_payload(progress: TaskProgress) -> dict[str, object]:
    """Validate and serialize only counters and safe phase identifiers."""

    if not isinstance(progress, TaskProgress):
        raise ValueError("progress must be a TaskProgress")
    if len(progress.phase_results) > 20:
        raise ValueError("phase_results exceeds the supported limit")
    current = _phase_payload(
        TaskProgressPhase(
            phase=progress.phase,
            requested=progress.requested,
            succeeded=progress.succeeded,
            failed=progress.failed,
            stored=progress.stored,
            count_unit=progress.count_unit,
            stored_count_unit=progress.stored_count_unit,
        )
    )
    return {
        **current,
        "phase_results": [_phase_payload(item) for item in progress.phase_results],
    }


def _phase_payload(phase: TaskProgressPhase) -> dict[str, object]:
    """Return one validated phase projection without accepting arbitrary text."""

    if not isinstance(phase, TaskProgressPhase) or not _SAFE_PROGRESS_TOKEN.fullmatch(phase.phase):
        raise ValueError("phase must be a safe identifier")
    for value in (phase.requested, phase.succeeded, phase.failed, phase.stored):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError("progress counters must be non-negative integers or null")
    for unit in (phase.count_unit, phase.stored_count_unit):
        if unit is not None and not _SAFE_PROGRESS_TOKEN.fullmatch(unit):
            raise ValueError("progress count units must be safe identifiers")
    return {
        "phase": phase.phase,
        "requested": phase.requested,
        "succeeded": phase.succeeded,
        "failed": phase.failed,
        "stored": phase.stored,
        "count_unit": phase.count_unit,
        "stored_count_unit": phase.stored_count_unit,
    }


def record_pending_task(
    *,
    task_id: str,
    task_name: str,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> None:
    """Persist one queued task so UI/API layers can see it before worker pickup."""
    RecordTaskExecutionUseCase(repository=get_task_record_repository()).execute(
        TaskExecutionRecord(
            task_id=task_id,
            task_name=task_name,
            status=TaskStatus.PENDING,
            args=args,
            kwargs=kwargs or {},
            started_at=None,
            finished_at=None,
            result=None,
            exception=None,
            traceback=None,
            runtime_seconds=None,
            retries=0,
            priority=TaskPriority.NORMAL,
            queue=None,
            worker=None,
        )
    )
