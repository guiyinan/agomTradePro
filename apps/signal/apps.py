"""Signal App Configuration"""

from django.apps import AppConfig


class SignalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.signal"
    verbose_name = "Investment Signals"

    def ready(self):
        """Import admin and tasks modules when app is ready"""
        import apps.signal.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.signal.interface.admin  # noqa: F401
        from apps.signal.application.asset_analysis_gateway import (
            register_asset_analysis_signal_gateway,
        )

        register_asset_analysis_signal_gateway()

        # Initialize domain config from database
        try:
            from apps.signal.infrastructure.config_init import initialize_domain_config

            initialize_domain_config()
        except Exception:
            # Development or database not migrated, ignore
            pass
