"""Isolated settings for the dormant sync identity persistence contract."""

from django.apps import AppConfig


class IsolatedAccountConfig(AppConfig):
    """Register Account models without production startup side effects."""

    name = "apps.account"
    label = "account"


SECRET_KEY = "data-center-sync-identity-test"
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "tests.settings_data_center_sync_identity.IsolatedAccountConfig",
    "tests.support.isolated_simulated_trading_app.apps.IsolatedSimulatedTradingConfig",
    "apps.data_center",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
MIGRATION_MODULES = {"account": None, "data_center": None, "simulated_trading": None}
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "core.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]
