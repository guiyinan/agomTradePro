"""Startup ordering contract for event-bus repository providers."""

from django.conf import settings


def test_alpha_trigger_registers_repository_before_events_initializes_bus() -> None:
    installed = list(settings.INSTALLED_APPS)
    assert installed.index("apps.alpha_trigger") < installed.index("apps.events")
