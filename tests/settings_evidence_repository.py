"""Isolated Django settings for the append-only Research Evidence ledgers."""

SECRET_KEY = "evidence-repository-test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.researchscopesourcev1app.EvidenceScopeSourceV1TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"research": None}
