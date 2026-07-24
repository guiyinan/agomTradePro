"""Signal App Configuration"""

from django.apps import AppConfig


class SignalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.signal"
    verbose_name = "Investment Signals"

    def ready(self) -> None:
        """Import admin and tasks modules when app is ready"""
        import apps.signal.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.signal.interface.admin  # noqa: F401
        from apps.signal.application.asset_analysis_gateway import (
            register_asset_analysis_signal_gateway,
        )
        from apps.signal.application.policy_gateway import register_signal_policy_gateway

        register_asset_analysis_signal_gateway()
        register_signal_policy_gateway()
        from core.integration.research_integrity_registry import (
            configure_forecast_entry_provider,
            configure_forecast_evaluation_recorder,
        )

        from .infrastructure.forecast_models import ForecastLedgerEntry
        from .infrastructure.forecast_repositories import ForecastEvaluationRepository

        configure_forecast_entry_provider(
            lambda: ForecastLedgerEntry._default_manager.select_related("outcome")
            .prefetch_related("evaluations")
            .filter(outcome__isnull=False)
        )
        forecast_repository = ForecastEvaluationRepository()
        configure_forecast_evaluation_recorder(forecast_repository.record_evaluation_for_signal)

        # Register the lazy database-backed Domain configuration provider.
        from apps.signal.infrastructure.config_init import initialize_domain_config

        initialize_domain_config()
