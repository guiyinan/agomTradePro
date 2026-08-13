"""Minimal Django 5.2 settings for Account 0041 ledger verification."""

SECRET_KEY = "account-0041-test"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "shared.apps.SharedConfig",
    "tests.settings_account_0041.Account0041TestConfig",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

from django.apps import AppConfig


class Account0041TestConfig(AppConfig):
    """Load Account models without production ready-time composition."""

    name = "tests.account0041app"
    label = "account"
