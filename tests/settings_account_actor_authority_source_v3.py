"""Isolated Django settings for actor-authority source v3 models."""

SECRET_KEY = "actor-authority-source-v3-test"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.actorauthoritysourcev3app.ActorAuthoritySourceV3TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}
