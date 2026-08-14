"""Isolated Django settings for the canonical system audit event schema."""

SECRET_KEY = "system-audit-event-test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.auditeventapp.AuditEventTestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"audit": None}
