"""
Core Django App Configuration

This is mainly for template tags and other core functionality.
"""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        """Register core production-readiness checks."""

        from core import checks  # noqa: F401
