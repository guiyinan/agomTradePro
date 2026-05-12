"""Helpers for development log file locations."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from datetime import UTC, datetime, timezone
from pathlib import Path

RUNSERVER_LOG_TIMESTAMP_ENV = "DJANGO_RUNSERVER_LOG_TIMESTAMP"
DEVELOPMENT_LOG_MAX_MB_ENV = "DJANGO_DEV_LOG_MAX_MB"
DEVELOPMENT_LOG_BACKUP_COUNT_ENV = "DJANGO_DEV_LOG_BACKUP_COUNT"
CELERY_LOG_MAX_MB_ENV = "CELERY_LOG_MAX_MB"
CELERY_LOG_BACKUP_COUNT_ENV = "CELERY_LOG_BACKUP_COUNT"
DEFAULT_DEVELOPMENT_LOG_MAX_MB = 20
DEFAULT_DEVELOPMENT_LOG_BACKUP_COUNT = 5
DEFAULT_CELERY_LOG_MAX_MB = 20
DEFAULT_CELERY_LOG_BACKUP_COUNT = 5
CELERY_WORKER_LOG_FILE_NAME = "celery-worker.log"
CELERY_BEAT_LOG_FILE_NAME = "celery-beat.log"


def get_or_create_runserver_log_timestamp(
    env: MutableMapping[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    """Return a stable timestamp for the current development server startup."""
    env_map = env if env is not None else os.environ
    existing_timestamp = env_map.get(RUNSERVER_LOG_TIMESTAMP_ENV, "").strip()
    if existing_timestamp:
        return existing_timestamp

    current_time = now or datetime.now(UTC).astimezone()
    timestamp = current_time.strftime("%Y%m%d-%H%M%S")
    env_map[RUNSERVER_LOG_TIMESTAMP_ENV] = timestamp
    return timestamp


def get_project_log_dir(base_dir: str | Path) -> Path:
    """Ensure and return the project-local log directory."""
    log_dir = Path(base_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_development_log_dir(base_dir: str | Path) -> Path:
    """Ensure and return the project-local development log directory."""
    return get_project_log_dir(base_dir)


def _get_positive_int(
    raw_value: str | None,
    default: int,
    minimum: int,
) -> int:
    """Parse a positive integer with fallback and lower-bound protection."""
    try:
        parsed_value = int((raw_value or "").strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed_value)


def get_development_log_max_bytes(env: MutableMapping[str, str] | None = None) -> int:
    """Return the per-file size limit for development server logs."""
    env_map = env if env is not None else os.environ
    max_mb = _get_positive_int(
        env_map.get(DEVELOPMENT_LOG_MAX_MB_ENV),
        default=DEFAULT_DEVELOPMENT_LOG_MAX_MB,
        minimum=1,
    )
    return max_mb * 1024 * 1024


def get_development_log_backup_count(env: MutableMapping[str, str] | None = None) -> int:
    """Return how many rotated development log files to keep per startup."""
    env_map = env if env is not None else os.environ
    return _get_positive_int(
        env_map.get(DEVELOPMENT_LOG_BACKUP_COUNT_ENV),
        default=DEFAULT_DEVELOPMENT_LOG_BACKUP_COUNT,
        minimum=1,
    )


def get_celery_log_max_bytes(env: MutableMapping[str, str] | None = None) -> int:
    """Return the per-file size limit for Celery logs."""
    env_map = env if env is not None else os.environ
    max_mb = _get_positive_int(
        env_map.get(CELERY_LOG_MAX_MB_ENV),
        default=DEFAULT_CELERY_LOG_MAX_MB,
        minimum=1,
    )
    return max_mb * 1024 * 1024


def get_celery_log_backup_count(env: MutableMapping[str, str] | None = None) -> int:
    """Return how many rotated Celery log files to keep."""
    env_map = env if env is not None else os.environ
    return _get_positive_int(
        env_map.get(CELERY_LOG_BACKUP_COUNT_ENV),
        default=DEFAULT_CELERY_LOG_BACKUP_COUNT,
        minimum=1,
    )


def get_runserver_log_path(
    base_dir: str | Path,
    env: MutableMapping[str, str] | None = None,
    now: datetime | None = None,
) -> Path:
    """Build the timestamped log file path for the current development server startup."""
    timestamp = get_or_create_runserver_log_timestamp(env=env, now=now)
    return get_project_log_dir(base_dir) / f"django-dev-{timestamp}.log"


def get_celery_worker_log_path(base_dir: str | Path) -> Path:
    """Build the project-local Celery worker log path."""
    return get_project_log_dir(base_dir) / CELERY_WORKER_LOG_FILE_NAME


def get_celery_beat_log_path(base_dir: str | Path) -> Path:
    """Build the project-local Celery beat log path."""
    return get_project_log_dir(base_dir) / CELERY_BEAT_LOG_FILE_NAME
