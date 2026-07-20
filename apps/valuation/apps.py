"""Django app configuration for valuation."""

from django.apps import AppConfig


class ValuationConfig(AppConfig):
    """Configure the canonical valuation owner."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.valuation"
    verbose_name = "估值引擎"
