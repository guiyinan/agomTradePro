"""Minimal Django 5.2 settings for the Account physical-row v2 ledger."""

from django.apps import AppConfig

SECRET_KEY = "account-v2-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_v2.AccountV2TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AccountV2TestConfig(AppConfig):
    """Load only the Account physical-row v2 model."""

    name = "tests.accountv2app"
    label = "account"
