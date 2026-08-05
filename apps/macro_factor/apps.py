"""Django configuration for the R3 macro-factor research App."""

from django.apps import AppConfig


class MacroFactorConfig(AppConfig):
    """Register the research-only macro-factor capability."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.macro_factor"
    verbose_name = "Macro Factor Research"
