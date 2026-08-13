"""Minimal settings for isolated methodology activation component tests."""

SECRET_KEY = "isolated-component-test"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
INSTALLED_APPS = ["apps.portfolio"]
MIGRATION_MODULES = {"portfolio": None}
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "TEST": {"NAME": ":memory:"},
    }
}
