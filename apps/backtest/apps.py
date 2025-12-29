"""Backtest App Configuration"""
from django.apps import AppConfig


class BacktestConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.backtest'
    verbose_name = 'Backtest Engine'
