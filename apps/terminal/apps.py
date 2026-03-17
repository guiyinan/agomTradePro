"""Django App Configuration for Terminal Module."""

from django.apps import AppConfig


class TerminalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.terminal'
    verbose_name = 'Terminal'
