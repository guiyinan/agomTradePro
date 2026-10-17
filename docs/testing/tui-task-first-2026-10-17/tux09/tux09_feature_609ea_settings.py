"""Disposable owner-only SQLite QA; no production database or network broker."""
from pathlib import Path
from core.settings.base import *
QA_ROOT = Path('D:\\githv\\agomTradePro\\.tmp\\tux09-feature-609ea-01')
DEBUG = True
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(QA_ROOT / "feature-default.sqlite3"), "OPTIONS": {"timeout": 30}, "TEST": {"NAME": str(QA_ROOT / "feature-tests.sqlite3")}}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tux09-feature-609ea-01"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
LOGGING = {"version": 1, "disable_existing_loggers": True, "handlers": {"console": {"class": "logging.StreamHandler"}}, "root": {"handlers": ["console"], "level": "WARNING"}}
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = False
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = False
CELERY_BEAT_SCHEDULE = {}
AUTOMATION_DEBUG_API_ENABLED = False
REALTIME_WEBSOCKET_ENABLED = False

TUX09_ARTIFACT_ROOT = QA_ROOT / "browser"
TUX08_ARTIFACT_ROOT = QA_ROOT / "research-browser"
