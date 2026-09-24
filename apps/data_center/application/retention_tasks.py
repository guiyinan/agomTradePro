"""Celery tasks for retention cleanup, planning, enforcement, and storage checks."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

from celery import shared_task

from apps.data_center.composition import (
    get_archive_coverage_gateway,
    get_raw_landing_repository,
    get_retention_plan_repository,
    get_retention_policy_repository,
    get_retention_run_repository,
    get_storage_hold_repository,
)
from core.integration.config_center_runtime import evaluate_storage_pressure
from shared.domain.task_outcomes import TaskBusinessOutcome

from .retention import (
    CreateRetentionPlanUseCase,
    EnforceRetentionPlanUseCase,
    RetentionCleanupUseCase,
)

logger = logging.getLogger(__name__)


def _retention_failure(
    *,
    operation: str,
    requested: int,
    error: str,
) -> dict[str, object]:
    """Build a stable failed retention-task contract without mutating data."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.FAILED.value,
        "operation": operation,
        "requested": requested,
        "succeeded": 0,
        "failed": 1,
        "stored": 0,
        "candidates": 0,
        "planned": 0,
        "deleted": 0,
        "held": 0,
        "blocked": 0,
        "bytes_planned": 0,
        "bytes_deleted": 0,
        "error": error,
    }


def _run_retention_pass(
    *,
    dataset_key: object,
    limit: object,
    dry_run: object,
    operation: str,
    confirm: object = True,
) -> dict[str, object]:
    """Run one bounded retention pass with task-boundary fail-closed guards."""

    if not isinstance(dataset_key, str) or not dataset_key.strip():
        return _retention_failure(operation=operation, requested=0, error="dataset_key is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        return _retention_failure(
            operation=operation,
            requested=0,
            error="limit must be between 1 and 10000",
        )
    if not isinstance(dry_run, bool):
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="dry_run must be a boolean",
        )
    if not isinstance(confirm, bool):
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="confirm must be a boolean",
        )
    if operation == "enforce" and not dry_run and not confirm:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": operation,
            "requested": limit,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "error": "explicit_confirmation_required",
        }

    try:
        disk = shutil.disk_usage(Path.cwd())
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used),
            actual_capacity_bytes=int(disk.total),
        )
    except Exception:
        logger.exception("Storage pressure evaluation failed before %s retention", operation)
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="storage_pressure_evaluation_failed",
        )
    if pressure.get("state") == "blocked":
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": operation,
            "requested": limit,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "storage": pressure,
            "error": str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive"),
        }

    try:
        result = RetentionCleanupUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_run_repository(),
        ).execute(dataset_key=dataset_key.strip(), limit=limit, dry_run=dry_run)
    except Exception:
        logger.exception("Retention %s failed for dataset=%s", operation, dataset_key.strip())
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="retention_execution_failed",
        )
    payload = result.to_dict()
    payload["operation"] = operation
    payload["storage"] = pressure
    return payload


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.cleanup_expired_raw_payloads_task",
    time_limit=900,
    soft_time_limit=840,
)
def cleanup_expired_raw_payloads_task(
    *,
    dataset_key: str,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, object]:
    """Keep the legacy task path as a non-mutating retention preview."""

    if dry_run is False:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": "cleanup",
            "requested": limit if isinstance(limit, int) and not isinstance(limit, bool) else 0,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "error": "legacy_cleanup_mutation_disabled_use_enforce",
        }

    return _run_retention_pass(
        dataset_key=dataset_key,
        limit=limit,
        dry_run=True,
        operation="cleanup",
    )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.plan_retention_task",
    time_limit=900,
    soft_time_limit=840,
)
def plan_retention_task(
    *,
    dataset_key: str,
    limit: int = 100,
    operation_id: str = "",
    ttl_hours: int = 24,
) -> dict[str, object]:
    """Persist an immutable exact-member plan without deleting anything."""

    if not isinstance(dataset_key, str) or not dataset_key.strip():
        return _retention_failure(operation="plan", requested=0, error="dataset_key is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        return _retention_failure(
            operation="plan", requested=0, error="limit must be between 1 and 10000"
        )
    if not isinstance(operation_id, str):
        return _retention_failure(
            operation="plan", requested=limit, error="operation_id must be a string"
        )
    if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int) or not 1 <= ttl_hours <= 168:
        return _retention_failure(
            operation="plan", requested=limit, error="ttl_hours must be between 1 and 168"
        )
    try:
        disk = shutil.disk_usage(Path.cwd())
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used), actual_capacity_bytes=int(disk.total)
        )
    except Exception:
        logger.exception("Storage pressure evaluation failed before retention planning")
        return _retention_failure(
            operation="plan", requested=limit, error="storage_pressure_evaluation_failed"
        )
    if pressure.get("state") == "blocked":
        return {
            **_retention_failure(
                operation="plan",
                requested=limit,
                error=str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive"),
            ),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "failed": 0,
            "storage": pressure,
        }
    try:
        result = CreateRetentionPlanUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_plan_repository(),
        ).execute(
            dataset_key=dataset_key.strip(),
            limit=limit,
            operation_id=operation_id.strip() or str(uuid4()),
            ttl_hours=ttl_hours,
        )
    except Exception:
        logger.exception("Retention plan creation failed for dataset=%s", dataset_key.strip())
        return _retention_failure(
            operation="plan", requested=limit, error="retention_plan_creation_failed"
        )
    payload = result.to_dict()
    payload["operation"] = "plan"
    payload["storage"] = pressure
    return payload


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.enforce_retention_task",
    time_limit=900,
    soft_time_limit=840,
)
def enforce_retention_task(
    *,
    plan_run_id: str = "",
    operation_id: str = "",
    confirm: bool = False,
) -> dict[str, object]:
    """Consume only an exact persisted plan after explicit confirmation."""

    if not isinstance(confirm, bool):
        return _retention_failure(
            operation="enforce", requested=0, error="confirm must be a boolean"
        )
    if not confirm:
        return {
            **_retention_failure(
                operation="enforce", requested=0, error="explicit_confirmation_required"
            ),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "failed": 0,
        }
    if not isinstance(plan_run_id, str) or not plan_run_id.strip():
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_run_id_required"
        )
    if not isinstance(operation_id, str) or not operation_id.strip():
        return _retention_failure(
            operation="enforce", requested=0, error="operation_id is required"
        )
    try:
        result = EnforceRetentionPlanUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_plan_repository(),
        ).execute(plan_id=plan_run_id.strip(), operation_id=operation_id.strip())
    except ValueError as exc:
        reason = str(exc)
        if reason in {"retention_plan_already_claimed", "retention_plan_already_completed"}:
            return {
                **_retention_failure(operation="enforce", requested=0, error=reason),
                "outcome": TaskBusinessOutcome.BLOCKED.value,
                "failed": 0,
            }
        logger.exception("Retention plan validation failed for plan=%s", plan_run_id.strip())
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_enforcement_failed"
        )
    except Exception:
        logger.exception("Retention plan enforcement failed for plan=%s", plan_run_id.strip())
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_enforcement_failed"
        )
    payload = result.to_dict()
    payload["operation"] = "enforce"
    return payload


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.verify_storage_budget_task",
    time_limit=300,
    soft_time_limit=240,
)
def verify_storage_budget_task(*, storage_path: str = "") -> dict[str, object]:
    """Check current filesystem pressure before another mutating batch."""

    if not isinstance(storage_path, str):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "blocked": 0,
            "error": "storage_path must be a string",
        }
    path = Path(storage_path.strip() or Path.cwd())
    try:
        disk = shutil.disk_usage(path)
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used),
            actual_capacity_bytes=int(disk.total),
        )
    except Exception:
        logger.exception("Storage budget verification failed for path=%s", path)
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "blocked": 0,
            "storage_path": str(path),
            "error": "storage_budget_verification_failed",
        }
    state = str(pressure.get("state") or "")
    if state == "blocked":
        outcome = TaskBusinessOutcome.BLOCKED
        succeeded = 0
        blocked = 1
        failed = 0
        error = str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive")
    elif state in {"critical", "emergency"}:
        outcome = TaskBusinessOutcome.BLOCKED
        succeeded = 0
        blocked = 1
        failed = 0
        error = f"storage_pressure_{state}"
    elif state == "warning":
        outcome = TaskBusinessOutcome.PARTIAL
        succeeded = 1
        blocked = 0
        failed = 0
        error = "storage_pressure_warning"
    elif state == "healthy":
        outcome = TaskBusinessOutcome.SUCCESS
        succeeded = 1
        blocked = 0
        failed = 0
        error = ""
    else:
        outcome = TaskBusinessOutcome.FAILED
        succeeded = 0
        blocked = 0
        failed = 1
        error = "storage_pressure_state_invalid"
    return {
        "success": outcome in {TaskBusinessOutcome.SUCCESS, TaskBusinessOutcome.NOOP},
        "outcome": outcome.value,
        "requested": 1,
        "succeeded": succeeded,
        "failed": failed,
        "blocked": blocked,
        "storage_path": str(path),
        "storage": pressure,
        "error": error,
    }
