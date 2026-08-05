"""Django application configuration for fixed-income research."""

from django.apps import AppConfig


class FixedIncomeConfig(AppConfig):
    """Register the research-only fixed-income capability."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fixed_income"
    verbose_name = "Fixed Income Research"
