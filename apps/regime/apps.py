"""Regime App Configuration"""
from django.apps import AppConfig


class RegimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.regime'
    verbose_name = 'Regime Engine'

    def ready(self):
        """Import admin module when app is ready"""
        import apps.regime.interface.admin  # noqa: F401
