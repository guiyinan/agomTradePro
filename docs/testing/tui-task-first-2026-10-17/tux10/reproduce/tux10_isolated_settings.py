"""Disposable local TUX10 settings; importing requires a future shared QA handoff."""

from pathlib import Path

from core.settings.base import *

QA_ROOT = Path(__file__).resolve().parent
DEBUG = True
# Explicit RequestFactory hosts used by the maintained SSL redirect tests.
ALLOWED_HOSTS = [
    "testserver",
    "localhost",
    "127.0.0.1",
    "web",
    "demo.agomtrade.pro",
    "web.attacker.example",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(QA_ROOT / "tux10-default.sqlite3"),
        "OPTIONS": {"timeout": 30},
        "TEST": {"NAME": str(QA_ROOT / "test_tux10.sqlite3")},
    }
}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "tux10-integrated-next-local",
    }
}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = False
CELERY_BEAT_SCHEDULE = {}
AUTOMATION_DEBUG_API_ENABLED = False
REALTIME_WEBSOCKET_ENABLED = False
TUX10_ARTIFACT_ROOT = QA_ROOT / "browser"

TUX08_ARTIFACT_ROOT = QA_ROOT / "source-artifacts"
