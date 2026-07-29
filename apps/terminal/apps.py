"""Django App Configuration for Terminal Module."""

from django.apps import AppConfig


class TerminalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.terminal"
    verbose_name = "Terminal"

    def ready(self) -> None:
        """Register Terminal-owned adapters after Django app initialization."""

        from .application.ai_capability_gateway import (
            register_ai_capability_terminal_gateway,
        )
        from .infrastructure.tui_metadata_signals import register_tui_metadata_cache_signals

        register_ai_capability_terminal_gateway()
        register_tui_metadata_cache_signals()
