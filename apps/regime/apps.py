"""Regime App Configuration"""

from django.apps import AppConfig


class RegimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.regime"
    verbose_name = "Regime Engine"

    def ready(self) -> None:
        """Import admin and tasks modules when app is ready"""
        import apps.regime.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.regime.interface.admin  # noqa: F401
        from apps.regime.application.pulse_gateway import register_regime_pulse_gateway

        register_regime_pulse_gateway()
