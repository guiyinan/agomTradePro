"""Minimal Django 5.2 settings for the allocated Physical-v3 ledger."""

from django.apps import AppConfig

SECRET_KEY = "allocated-physical-v3-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_allocated_physical_v3.AllocatedPhysicalV3TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AllocatedPhysicalV3TestConfig(AppConfig):
    """Load only the allocated Physical-v3 ledger model."""

    name = "tests.allocatedphysicalv3app"
    label = "account"
