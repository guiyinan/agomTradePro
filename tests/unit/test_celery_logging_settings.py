import importlib
import sys


def _reload_module(module_name: str):
    """Reload a settings module so environment overrides are applied."""
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_development_settings_define_project_local_celery_log_files() -> None:
    """Development settings should route Celery worker and beat logs into logs/."""
    settings_module = _reload_module("core.settings.development")

    worker_handler = settings_module.LOGGING["handlers"]["celery_worker_file"]
    beat_handler = settings_module.LOGGING["handlers"]["celery_beat_file"]
    worker_filename = worker_handler["filename"].replace("\\", "/")
    beat_filename = beat_handler["filename"].replace("\\", "/")

    assert worker_filename.endswith("logs/celery-worker.log")
    assert beat_filename.endswith("logs/celery-beat.log")
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
    worker_filename = worker_handler["filename"].replace("\\", "/")
    beat_filename = beat_handler["filename"].replace("\\", "/")

    assert worker_filename.endswith("logs/celery-worker.log")
    assert beat_filename.endswith("logs/celery-beat.log")
    assert worker_handler["maxBytes"] == 20 * 1024 * 1024
    assert worker_handler["backupCount"] == 5
    assert beat_handler["maxBytes"] == 20 * 1024 * 1024
    assert beat_handler["backupCount"] == 5
    assert settings_module.LOGGING["loggers"]["celery.beat"]["handlers"][-1] == "celery_beat_file"
