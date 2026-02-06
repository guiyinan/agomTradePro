"""
Django app configuration for strategy module.
"""
from django.apps import AppConfig


class StrategyConfig(AppConfig):
    """Strategy app configuration"""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.strategy'
    verbose_name = '投资组合策略系统'

