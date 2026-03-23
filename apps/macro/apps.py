"""Macro App Configuration"""
from django.apps import AppConfig


class MacroConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.macro'
    verbose_name = 'Macro Data'

    def ready(self):
        """Import admin and tasks modules when app is ready"""
        import apps.macro.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.macro.interface.admin  # noqa: F401

        # Register the database secrets loader with shared.config.secrets
        # This allows secrets.py to load from database without directly importing from apps/
        try:
            from apps.macro.infrastructure.secrets_loader import load_secrets_from_database
            from shared.config.secrets import register_database_secrets_loader
            register_database_secrets_loader(load_secrets_from_database)
        except Exception:
            # Ignore errors during development or if shared is not available
            pass
