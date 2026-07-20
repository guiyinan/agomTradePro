"""Django application configuration for operational readiness."""

from django.apps import AppConfig


class OperationalReadinessConfig(AppConfig):
    """Register the operational-readiness capability without owning ORM models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operational_readiness"
    verbose_name = "Operational Readiness"
