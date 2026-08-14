"""Minimal SQLite settings for the system-audit schema component tests."""

SECRET_KEY = "system-audit-schema-test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.auditsystemapp.apps.AuditSystemTestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"audit": None}
