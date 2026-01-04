"""
Simulated Trading App Configuration
"""
from django.apps import AppConfig


class SimulatedTradingConfig(AppConfig):
    """模拟盘自动交易应用配置"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.simulated_trading'
    verbose_name = '模拟盘自动交易'
