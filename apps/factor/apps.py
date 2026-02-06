"""Factor app configuration"""
from django.apps import AppConfig


class FactorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.factor'
    verbose_name = '因子选股'
