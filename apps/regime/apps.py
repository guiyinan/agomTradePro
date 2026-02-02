"""Regime App Configuration"""
from django.apps import AppConfig


class RegimeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.regime'
    verbose_name = 'Regime Engine'

    def ready(self):
        """Import admin and tasks modules when app is ready"""
        import apps.regime.interface.admin  # noqa: F401
        import apps.regime.infrastructure.admin  # noqa: F401 - 增强的 Admin 配置
        import apps.regime.application.tasks  # noqa: F401 - Import Celery tasks
