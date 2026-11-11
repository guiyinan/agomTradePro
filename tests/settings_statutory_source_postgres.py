"""Bound Source-only QA to an existing, production-migrated critical test database.

The component fixture rejects missing migration/trigger evidence. This profile
does not establish schema qualification or replace full-profile CI migration.
"""

from __future__ import annotations

from importlib import import_module

from django.apps import AppConfig
from django.urls import URLPattern, URLResolver

from core.settings.critical_postgres_test import *  # noqa: F403


class StatutorySourceTestConfig(AppConfig):
    """Register the actual four production models without unrelated startup jobs."""

    name = "apps.data_center"
    label = "data_center"

    def import_models(self) -> None:
        """Load the exact production Source models used by migration 0111."""
        self.models = self.apps.all_models[self.label]
        self.models_module = import_module(
            "apps.data_center.infrastructure.statutory_source_models"
        )


INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "tests.settings_statutory_source_postgres.StatutorySourceTestConfig",
]
MIGRATION_MODULES = {"data_center": None}
MIDDLEWARE: list[str] = []
REST_FRAMEWORK: dict[str, object] = {}
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ash05-statutory-source-native",
    }
}
ROOT_URLCONF = __name__
urlpatterns: list[URLPattern | URLResolver] = []
