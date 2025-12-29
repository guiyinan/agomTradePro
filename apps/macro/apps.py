"""Macro App Configuration"""
from django.apps import AppConfig


class MacroConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.macro'
    verbose_name = 'Macro Data'

    def ready(self):
        """Import admin module when app is ready"""
        import apps.macro.interface.admin  # noqa: F401
