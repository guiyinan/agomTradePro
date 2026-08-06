"""Celery tasks owned by the Config Center application layer."""

from __future__ import annotations

import logging
import os

from celery import shared_task

from apps.config_center.application.decision_readiness_guard_tasks import (
    audit_decision_readiness_task,
)
from apps.config_center.application.public import (
    StorageCapacityProfileBlockedError,
    collect_and_record_storage_capacity_profile,
)
from shared.domain.task_outcomes import TaskBusinessOutcome

logger = logging.getLogger(__name__)


def _default_runtime_environment() -> str:
    """Resolve the task environment without inventing a storage policy."""

    settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE") or "").strip()
    return "production" if settings_module.endswith(".production") else "development"


def _capacity_task_result(
    *,
    outcome: TaskBusinessOutcome,
    environment: str,
    observation_id: str = "",
    pressure_state: str = "",
    error: str = "",
) -> dict[str, object]:
    """Build the normalized Celery business-outcome contract."""

    succeeded = 1 if outcome is TaskBusinessOutcome.SUCCESS else 0
    failed = 1 if outcome is TaskBusinessOutcome.FAILED else 0
    blocked = 1 if outcome is TaskBusinessOutcome.BLOCKED else 0
    stored = 1 if outcome is TaskBusinessOutcome.SUCCESS else 0
    return {
        "success": outcome is TaskBusinessOutcome.SUCCESS,
        "outcome": outcome.value,
        "requested": 1,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        "blocked": blocked,
        "environment": environment,
        "observation_id": observation_id,
        "pressure_state": pressure_state,
        "error": error,
    }


@shared_task(  # type: ignore[misc]
    name="apps.config_center.application.tasks.collect_storage_capacity_profile_task",
    time_limit=300,
    soft_time_limit=240,
)
def collect_storage_capacity_profile_task(
    *,
    environment: str = "",
    source: str = "celery-hourly-observer",
) -> dict[str, object]:
    """Collect hourly capacity evidence and fail closed without an active policy."""

    if not isinstance(environment, str) or not isinstance(source, str):
        return _capacity_task_result(
            outcome=TaskBusinessOutcome.FAILED,
            environment="",
            error="environment and source must be strings",
        )
    normalized_environment = environment.strip() or _default_runtime_environment()
    normalized_source = source.strip()
    if not normalized_source:
        return _capacity_task_result(
            outcome=TaskBusinessOutcome.FAILED,
            environment=normalized_environment,
            error="source cannot be empty",
        )
    try:
        observation = collect_and_record_storage_capacity_profile(
            environment=normalized_environment,
            source=normalized_source,
        )
    except StorageCapacityProfileBlockedError as exc:
        return _capacity_task_result(
            outcome=TaskBusinessOutcome.BLOCKED,
            environment=normalized_environment,
            error=str(exc),
        )
    except Exception:
        logger.exception(
            "Storage capacity profile collection failed for environment=%s",
            normalized_environment,
        )
        return _capacity_task_result(
            outcome=TaskBusinessOutcome.FAILED,
            environment=normalized_environment,
            error="storage_capacity_profile_collection_failed",
        )
    return _capacity_task_result(
        outcome=TaskBusinessOutcome.SUCCESS,
        environment=normalized_environment,
        observation_id=observation.observation_id,
        pressure_state=observation.pressure_state,
    )


__all__ = ["audit_decision_readiness_task", "collect_storage_capacity_profile_task"]
