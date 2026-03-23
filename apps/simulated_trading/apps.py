"""
Simulated Trading App Configuration
"""
from django.apps import AppConfig


class SimulatedTradingConfig(AppConfig):
    """模拟盘自动交易应用配置"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.simulated_trading'
    verbose_name = '模拟盘自动交易'

    def ready(self):
        """Import admin and tasks modules when app is ready"""
        import apps.simulated_trading.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.simulated_trading.interface.admin  # noqa: F401
