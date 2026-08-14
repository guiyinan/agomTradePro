"""Minimal Django settings for canonical Account creation ledger models."""

from django.apps import AppConfig

SECRET_KEY = "canonical-account-creation-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_creation.AccountCreationTestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AccountCreationTestConfig(AppConfig):
    """Load only canonical Account creation ledger models."""

    name = "tests.accountcreationapp"
    label = "account"
