"""Minimal Django 5.2 settings for canonical creation consumption ledgers."""

from django.apps import AppConfig

SECRET_KEY = "canonical-account-creation-consumption-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_creation_consumption.AccountCreationConsumptionTestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AccountCreationConsumptionTestConfig(AppConfig):
    """Load only models required by the 0047 expand schema."""

    name = "tests.accountcreationconsumptionapp"
    label = "account"
