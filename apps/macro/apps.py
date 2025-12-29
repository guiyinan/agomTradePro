"""Macro App Configuration"""
from django.apps import AppConfig


class MacroConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.macro'
    verbose_name = 'Macro Data'
