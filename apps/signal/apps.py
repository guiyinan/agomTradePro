"""Signal App Configuration"""
from django.apps import AppConfig


class SignalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.signal'
    verbose_name = 'Investment Signals'
