"""Factor app configuration"""

from django.apps import AppConfig


class FactorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.factor"
    verbose_name = "因子选股"

    def ready(self) -> None:
        """Register Factor-owned providers without importing consumers."""

        from apps.factor.application.repository_provider import (
            get_factor_integration_service,
        )
        from core.integration.unified_signal_registry import (
            register_factor_service_factory,
        )

        register_factor_service_factory(get_factor_integration_service)
