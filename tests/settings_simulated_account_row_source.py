"""Minimal Django 5.2 settings for the simulated account-row source ledger."""

from django.apps import AppConfig

SECRET_KEY = "simulated-row-source-test"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "tests.settings_simulated_account_row_source.SimulatedRowSourceTestConfig",
]


class SimulatedRowSourceTestConfig(AppConfig):
    """Load only the isolated source ledger model."""

    name = "tests.simulatedrowapp"
    label = "simulated_trading"
