"""Conditional Django app for the disposable M5 calendar test transport."""

from __future__ import annotations

from django.apps import AppConfig


class M5CalendarTransportConfig(AppConfig):
    """Install one guarded synthetic calendar-source composition hook."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.support.tui_research"
    label = "m5_calendar_transport_test_support"

    def ready(self) -> None:
        """Repeat isolation checks and install without accessing the database."""

        from .calendar_transport_runtime import install_m5_calendar_transport

        install_m5_calendar_transport()
