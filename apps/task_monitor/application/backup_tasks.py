"""Governed Celery tasks for verified database backup operations."""

from __future__ import annotations

import gzip
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Any

from celery import shared_task

from apps.task_monitor.application.backup_capacity import (
    BLOCKING_BACKUP_PRESSURE_STATES,
    collect_backup_capacity_report,
)
from apps.task_monitor.application.repository_provider import get_database_backup_service

logger = logging.getLogger(__name__)


def _validate_backup_inputs(
    *,
    keep_days: int | None,
    compress: bool,
    output_dir: str | None,
) -> str | None:
    """Return a stable validation reason before any capacity or backup I/O."""

    if keep_days is not None and (
        isinstance(keep_days, bool) or not isinstance(keep_days, int) or not 1 <= keep_days <= 3650
    ):
        return "keep_days_must_be_between_1_and_3650"
    if not isinstance(compress, bool):
        return "compress_must_be_boolean"
    if output_dir is not None and (not isinstance(output_dir, str) or not output_dir.strip()):
        return "output_dir_must_be_non_empty_string"
    return None


@shared_task(  # type: ignore[misc]
    bind=True,
    name="apps.task_monitor.application.tasks.backup_database_task",
    max_retries=3,
    default_retry_delay=300,
    time_limit=300,
    soft_time_limit=280,
)
def backup_database_task(
    self: Any,
    keep_days: int | None = None,
    compress: bool = True,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Create one verified backup after a fail-closed storage preflight."""

    validation_error = _validate_backup_inputs(
        keep_days=keep_days,
        compress=compress,
        output_dir=output_dir,
    )
    if validation_error:
        return {
            "outcome": "failed",
            "success": False,
            "reason": validation_error,
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }

    try:
        capacity = collect_backup_capacity_report()
    except Exception as exc:
        logger.warning(
            "Database backup blocked by unavailable capacity evidence: %s",
            exc.__class__.__name__,
        )
        return {
            "outcome": "blocked",
            "success": False,
            "reason": "storage_capacity_evidence_unavailable",
            "requested": 1,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
        }

    pressure_state = str(capacity.get("state", "blocked"))
    if pressure_state in BLOCKING_BACKUP_PRESSURE_STATES:
        return {
            "outcome": "blocked",
            "success": False,
            "reason": str(capacity.get("reason", "storage_pressure_blocked")),
            "capacity": capacity,
            "requested": 1,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
        }

    try:
        result = get_database_backup_service().backup_database(
            keep_days=keep_days,
            compress=compress,
            output_dir=output_dir,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("Database backup command failed: %s", exc.__class__.__name__)
        raise self.retry(exc=exc) from exc
    except Exception:
        logger.exception("Database backup task failed")
        raise

    return {
        "outcome": "success",
        "success": True,
        "reason": "verified_backup_created",
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 1,
        "backup_file": result.backup_file,
        "keep_days": result.keep_days,
        "compressed": result.compressed,
        "removed_old_backups": result.removed_old_backups,
        "engine": result.engine,
        "backup_format": result.backup_format,
        "size_bytes": result.size_bytes,
        "sha256": result.sha256,
        "capacity": capacity,
    }


def _sha256_file(path: Path) -> str:
    """Return a streaming digest without loading the backup into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@shared_task(  # type: ignore[misc]
    name="apps.task_monitor.application.tasks.verify_backup_task",
    time_limit=300,
    soft_time_limit=280,
)
def verify_backup_task(
    backup_file: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify artifact size, format readability, and optional SHA-256 evidence."""

    if not isinstance(backup_file, str) or not backup_file.strip():
        return {
            "outcome": "failed",
            "success": False,
            "reason": "backup_file_must_be_non_empty_string",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }
    if expected_sha256 is not None and (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_sha256)
    ):
        return {
            "outcome": "failed",
            "success": False,
            "reason": "expected_sha256_invalid",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }

    backup_path = Path(backup_file)
    if not backup_path.is_file():
        return {
            "outcome": "failed",
            "success": False,
            "reason": "backup_file_not_found",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }
    file_size = backup_path.stat().st_size
    if file_size == 0:
        return {
            "outcome": "failed",
            "success": False,
            "reason": "backup_file_empty",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }

    try:
        if backup_path.suffix == ".dump":
            subprocess.run(
                ["pg_restore", "--list", str(backup_path)],
                capture_output=True,
                text=True,
                check=True,
            )
        elif backup_path.suffix == ".gz":
            with gzip.open(backup_path, "rb") as stream:
                stream.read(1024)
        digest = _sha256_file(backup_path)
    except Exception as exc:
        logger.warning("Backup verification failed: %s", exc.__class__.__name__)
        return {
            "outcome": "failed",
            "success": False,
            "reason": "backup_artifact_unreadable",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
        }

    if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
        return {
            "outcome": "failed",
            "success": False,
            "reason": "backup_sha256_mismatch",
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "stored": 0,
            "sha256": digest,
        }
    return {
        "outcome": "success",
        "success": True,
        "reason": "backup_artifact_verified",
        "requested": 1,
        "succeeded": 1,
        "failed": 0,
        "stored": 0,
        "backup_file": str(backup_path),
        "file_size": file_size,
        "sha256": digest,
    }


__all__ = ["backup_database_task", "verify_backup_task"]
