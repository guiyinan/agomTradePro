from datetime import UTC, datetime
from pathlib import Path

from core.log_file_paths import (
    CELERY_LOG_BACKUP_COUNT_ENV,
    CELERY_LOG_MAX_MB_ENV,
    DEFAULT_CELERY_LOG_BACKUP_COUNT,
    DEFAULT_CELERY_LOG_MAX_MB,
    DEFAULT_DEVELOPMENT_LOG_BACKUP_COUNT,
    DEFAULT_DEVELOPMENT_LOG_MAX_MB,
    DEVELOPMENT_LOG_BACKUP_COUNT_ENV,
    DEVELOPMENT_LOG_MAX_MB_ENV,
    RUNSERVER_LOG_TIMESTAMP_ENV,
    get_celery_beat_log_path,
    get_celery_log_backup_count,
    get_celery_log_max_bytes,
    get_celery_worker_log_path,
    get_development_log_backup_count,
    get_development_log_max_bytes,
    get_or_create_runserver_log_timestamp,
    get_runserver_log_path,
)


def test_get_or_create_runserver_log_timestamp_reuses_existing_value() -> None:
    """Existing startup timestamps should be reused across reloads."""
    env = {RUNSERVER_LOG_TIMESTAMP_ENV: "20260403-103000"}

    timestamp = get_or_create_runserver_log_timestamp(env=env)

    assert timestamp == "20260403-103000"


def test_get_or_create_runserver_log_timestamp_persists_generated_value() -> None:
    """Generated startup timestamps should be written back into the environment."""
    env: dict[str, str] = {}
    fixed_now = datetime(2026, 4, 3, 2, 30, 45, tzinfo=UTC)

    timestamp = get_or_create_runserver_log_timestamp(env=env, now=fixed_now)

    assert timestamp == "20260403-023045"
    assert env[RUNSERVER_LOG_TIMESTAMP_ENV] == timestamp


def test_get_runserver_log_path_creates_timestamped_file_under_project_logs(tmp_path: Path) -> None:
    """Development logs should be written to the local logs directory."""
    env: dict[str, str] = {}
    fixed_now = datetime(2026, 4, 3, 2, 30, 45, tzinfo=UTC)

    log_path = get_runserver_log_path(tmp_path, env=env, now=fixed_now)

    assert log_path == tmp_path / "logs" / "django-dev-20260403-023045.log"
    assert log_path.parent.is_dir()


def test_get_celery_worker_log_path_uses_project_logs_directory(tmp_path: Path) -> None:
    """Celery worker logs should be written to the local logs directory."""
    log_path = get_celery_worker_log_path(tmp_path)

    assert log_path == tmp_path / "logs" / "celery-worker.log"
    assert log_path.parent.is_dir()


def test_get_celery_beat_log_path_uses_project_logs_directory(tmp_path: Path) -> None:
    """Celery beat logs should be written to the local logs directory."""
    log_path = get_celery_beat_log_path(tmp_path)

    assert log_path == tmp_path / "logs" / "celery-beat.log"
    assert log_path.parent.is_dir()


def test_get_development_log_max_bytes_uses_reasonable_default() -> None:
    """Development log files should default to a bounded size."""
    max_bytes = get_development_log_max_bytes(env={})

    assert max_bytes == DEFAULT_DEVELOPMENT_LOG_MAX_MB * 1024 * 1024


def test_get_development_log_max_bytes_honors_env_override() -> None:
    """Per-file log size should be configurable via environment variable."""
    max_bytes = get_development_log_max_bytes(env={DEVELOPMENT_LOG_MAX_MB_ENV: "8"})

    assert max_bytes == 8 * 1024 * 1024


def test_get_development_log_backup_count_uses_reasonable_default() -> None:
    """Development log rotation should keep a bounded number of backups."""
    backup_count = get_development_log_backup_count(env={})

    assert backup_count == DEFAULT_DEVELOPMENT_LOG_BACKUP_COUNT


def test_get_development_log_backup_count_honors_env_override() -> None:
    """Backup count should be configurable via environment variable."""
    backup_count = get_development_log_backup_count(
        env={DEVELOPMENT_LOG_BACKUP_COUNT_ENV: "7"}
    )

    assert backup_count == 7


def test_get_celery_log_max_bytes_uses_reasonable_default() -> None:
    """Celery log files should default to a bounded size."""
    max_bytes = get_celery_log_max_bytes(env={})

    assert max_bytes == DEFAULT_CELERY_LOG_MAX_MB * 1024 * 1024


def test_get_celery_log_max_bytes_honors_env_override() -> None:
    """Celery log size should be configurable via environment variable."""
    max_bytes = get_celery_log_max_bytes(env={CELERY_LOG_MAX_MB_ENV: "12"})

    assert max_bytes == 12 * 1024 * 1024


def test_get_celery_log_backup_count_uses_reasonable_default() -> None:
    """Celery log rotation should keep a bounded number of backups."""
    backup_count = get_celery_log_backup_count(env={})

    assert backup_count == DEFAULT_CELERY_LOG_BACKUP_COUNT


def test_get_celery_log_backup_count_honors_env_override() -> None:
    """Celery backup count should be configurable via environment variable."""
    backup_count = get_celery_log_backup_count(
        env={CELERY_LOG_BACKUP_COUNT_ENV: "6"}
    )

    assert backup_count == 6
