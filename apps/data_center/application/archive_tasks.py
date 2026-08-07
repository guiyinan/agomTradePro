"""Governed Celery entrypoints for the trusted archive lifecycle."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.data_center.composition import (
    get_archive_candidate_repository,
    get_archive_capacity_guard,
    get_archive_manifest_repository,
    get_dataset_contract_repository,
    get_raw_archive_store,
    get_retention_policy_repository,
)
from shared.domain.task_outcomes import TaskBusinessOutcome

from .archive import (
    ArchiveRawPayloadsUseCase,
    AuditArchiveRestoreUseCase,
    VerifyStoredArchiveUseCase,
)

logger = logging.getLogger(__name__)


def _failure(
    *,
    operation: str,
    outcome: TaskBusinessOutcome,
    reason: str,
    archive_id: str = "",
    dataset_key: str = "",
    requested: int = 1,
) -> dict[str, object]:
    """Build a stable fail-closed archive task payload."""

    return {
        "success": False,
        "outcome": outcome.value,
        "operation": operation,
        "archive_id": archive_id,
        "dataset_key": dataset_key,
        "requested": requested,
        "candidates": 0,
        "succeeded": 0,
        "failed": 1 if outcome is TaskBusinessOutcome.FAILED else 0,
        "stored": 0,
        "object_count": 0,
        "size_bytes": 0,
        "reason": reason,
    }


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.archive_tasks.archive_raw_payloads_task",
    time_limit=1800,
    soft_time_limit=1740,
)
def archive_raw_payloads_task(
    *,
    dataset_key: str,
    limit: int = 100,
) -> dict[str, object]:
    """Export one bounded RawPayload batch without deleting source rows."""

    if not isinstance(dataset_key, str) or not dataset_key.strip():
        return _failure(
            operation="export",
            outcome=TaskBusinessOutcome.FAILED,
            reason="dataset_key is required",
            requested=0,
        )
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        return _failure(
            operation="export",
            outcome=TaskBusinessOutcome.FAILED,
            reason="limit must be between 1 and 10000",
            dataset_key=dataset_key.strip(),
            requested=0,
        )
    try:
        use_case = ArchiveRawPayloadsUseCase(
            get_retention_policy_repository(),
            get_dataset_contract_repository(),
            get_archive_candidate_repository(),
            get_archive_manifest_repository(),
            get_raw_archive_store(),
            get_archive_capacity_guard(),
        )
    except RuntimeError as exc:
        return _failure(
            operation="export",
            outcome=TaskBusinessOutcome.BLOCKED,
            reason=str(exc),
            dataset_key=dataset_key.strip(),
            requested=limit,
        )
    try:
        return use_case.execute(dataset_key=dataset_key.strip(), limit=limit).to_dict()
    except Exception:
        logger.exception("Raw archive export failed for dataset=%s", dataset_key.strip())
        return _failure(
            operation="export",
            outcome=TaskBusinessOutcome.FAILED,
            reason="archive_export_failed",
            dataset_key=dataset_key.strip(),
            requested=limit,
        )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.verify_archive_manifest_task",
    time_limit=900,
    soft_time_limit=840,
)
def verify_archive_manifest_task(*, archive_id: str) -> dict[str, object]:
    """Verify one manifest only by independently reading configured cold bytes."""

    if not isinstance(archive_id, str) or not archive_id.strip():
        return _failure(
            operation="verify",
            outcome=TaskBusinessOutcome.FAILED,
            reason="archive_id is required",
            requested=0,
        )
    try:
        use_case = VerifyStoredArchiveUseCase(
            get_archive_manifest_repository(),
            get_raw_archive_store(),
        )
    except RuntimeError as exc:
        return _failure(
            operation="verify",
            outcome=TaskBusinessOutcome.BLOCKED,
            reason=str(exc),
            archive_id=archive_id.strip(),
        )
    try:
        return use_case.execute(archive_id=archive_id.strip()).to_dict()
    except Exception:
        logger.exception("Archive verification failed for archive_id=%s", archive_id.strip())
        return _failure(
            operation="verify",
            outcome=TaskBusinessOutcome.FAILED,
            reason="archive_verification_failed",
            archive_id=archive_id.strip(),
        )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.archive_tasks.audit_archive_restore_task",
    time_limit=1800,
    soft_time_limit=1740,
)
def audit_archive_restore_task(*, archive_id: str, operation_id: str) -> dict[str, object]:
    """Perform and persist one idempotent isolated staging restore."""

    if not isinstance(archive_id, str) or not archive_id.strip():
        return _failure(
            operation="restore",
            outcome=TaskBusinessOutcome.FAILED,
            reason="archive_id is required",
            requested=0,
        )
    if not isinstance(operation_id, str) or not operation_id.strip():
        return _failure(
            operation="restore",
            outcome=TaskBusinessOutcome.FAILED,
            reason="operation_id is required",
            archive_id=archive_id.strip(),
            requested=0,
        )
    try:
        use_case = AuditArchiveRestoreUseCase(
            get_archive_manifest_repository(),
            get_raw_archive_store(),
        )
    except RuntimeError as exc:
        return _failure(
            operation="restore",
            outcome=TaskBusinessOutcome.BLOCKED,
            reason=str(exc),
            archive_id=archive_id.strip(),
        )
    try:
        return use_case.execute(
            archive_id=archive_id.strip(),
            operation_id=operation_id.strip(),
        ).to_dict()
    except Exception:
        logger.exception("Archive restore audit failed for archive_id=%s", archive_id.strip())
        return _failure(
            operation="restore",
            outcome=TaskBusinessOutcome.FAILED,
            reason="archive_restore_audit_failed",
            archive_id=archive_id.strip(),
        )


__all__ = [
    "archive_raw_payloads_task",
    "audit_archive_restore_task",
    "verify_archive_manifest_task",
]
