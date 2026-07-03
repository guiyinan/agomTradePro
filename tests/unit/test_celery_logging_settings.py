import importlib
import sys
from pathlib import PurePath


def _reload_module(module_name: str):
    """Reload a settings module so environment overrides are applied."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def _assert_process_local_celery_log_name(filename: str, prefix: str) -> None:
    """Assert Celery rotating file handlers do not share a single process-wide file."""
    name = PurePath(filename).name
    assert filename.replace("\\", "/").endswith(f"logs/{name}")
    assert name.startswith(f"{prefix}-")
    assert name.endswith(".log")
    assert name != f"{prefix}.log"


def test_development_settings_define_project_local_celery_log_files() -> None:
    """Development settings should route Celery worker and beat logs into logs/."""
    settings_module = _reload_module("core.settings.development")

    worker_handler = settings_module.LOGGING["handlers"]["celery_worker_file"]
    beat_handler = settings_module.LOGGING["handlers"]["celery_beat_file"]
    _assert_process_local_celery_log_name(worker_handler["filename"], "celery-worker")
    _assert_process_local_celery_log_name(beat_handler["filename"], "celery-beat")
    assert worker_handler["maxBytes"] == 20 * 1024 * 1024
    assert worker_handler["backupCount"] == 5
    assert beat_handler["maxBytes"] == 20 * 1024 * 1024
    assert beat_handler["backupCount"] == 5
    assert settings_module.LOGGING["loggers"]["celery.beat"]["handlers"][-1] == "celery_beat_file"


def test_production_settings_define_project_local_celery_log_files(monkeypatch) -> None:
    """Production settings should also route Celery worker and beat logs into logs/."""
    monkeypatch.setenv("SECRET_KEY", "a" * 50)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("CELERY_LOG_MAX_MB", raising=False)
    monkeypatch.delenv("CELERY_LOG_BACKUP_COUNT", raising=False)

    settings_module = _reload_module("core.settings.production")

    worker_handler = settings_module.LOGGING["handlers"]["celery_worker_file"]
    beat_handler = settings_module.LOGGING["handlers"]["celery_beat_file"]
    _assert_process_local_celery_log_name(worker_handler["filename"], "celery-worker")
    _assert_process_local_celery_log_name(beat_handler["filename"], "celery-beat")
    assert worker_handler["maxBytes"] == 20 * 1024 * 1024
    assert worker_handler["backupCount"] == 5
    assert beat_handler["maxBytes"] == 20 * 1024 * 1024
    assert beat_handler["backupCount"] == 5
    assert settings_module.LOGGING["loggers"]["celery.beat"]["handlers"][-1] == "celery_beat_file"
