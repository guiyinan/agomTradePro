"""Minimal Django settings for Account owner-assignment evidence v2 models."""

from django.apps import AppConfig

SECRET_KEY = "account-assignment-v2-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_assignment_v2.AccountAssignmentV2TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AccountAssignmentV2TestConfig(AppConfig):
    """Load only the two Account owner-assignment evidence v2 models."""

    name = "tests.accountassignmentv2app"
    label = "account"
