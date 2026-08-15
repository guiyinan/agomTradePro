"""Isolated Django settings for the dormant Evidence scope-source v1 ledger."""

SECRET_KEY = "evidence-scope-source-v1-test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.researchscopesourcev1app.EvidenceScopeSourceV1TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"research": None}
