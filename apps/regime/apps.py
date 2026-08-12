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
        from apps.regime.historical_assignment_composition import (
            build_historical_regime_assignment_runtime,
        )
        from core.integration.r3_owner_evidence import configure_r3_regime_assignment_factory

        register_regime_pulse_gateway()
        configure_r3_regime_assignment_factory(
            lambda using: build_historical_regime_assignment_runtime(using=using).repository
        )
