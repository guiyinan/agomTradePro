"""Backtest App Configuration"""
from django.apps import AppConfig


class BacktestConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.backtest'
    verbose_name = 'Backtest Engine'

    def ready(self):
        """Import admin and tasks modules when app is ready"""
        import apps.backtest.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.backtest.interface.admin  # noqa: F401
