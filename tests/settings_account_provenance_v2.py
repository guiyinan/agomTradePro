"""Minimal Django 5.2 settings for generating the Account provenance v2 ledger."""

from django.apps import AppConfig

SECRET_KEY = "account-provenance-v2-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_provenance_v2.AccountProvenanceV2TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None}


class AccountProvenanceV2TestConfig(AppConfig):
    """Load only the Account provenance receipt v2 model."""

    name = "tests.accountprovv2app"
    label = "account"
