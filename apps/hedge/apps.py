"""Hedge app configuration"""
from django.apps import AppConfig


class HedgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hedge'
    verbose_name = '对冲组合'
