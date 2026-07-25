"""Event bus startup wiring regressions."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.events.application import event_bus_initializer
from apps.events.application.event_bus_initializer import EventBusInitializer
from apps.events.domain import services
from apps.events.domain.entities import DomainEvent, EventHandler, EventType
from apps.events.domain.registry import EventSubscriberRegistry
from apps.events.domain.services import EventBus, InMemoryEventBus


class _BusAwareHandler(EventHandler):
    def __init__(self) -> None:
        self.event_bus: EventBus | None = None

    def can_handle(self, event_type: EventType) -> bool:
        return event_type is EventType.REGIME_CHANGED

    def handle(self, event: DomainEvent) -> None:
        return None


def _registry_with(
    factory: Callable[[], EventHandler],
) -> EventSubscriberRegistry:
    registry = EventSubscriberRegistry()
    registry.register(
        module_name="test_subscriber",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=factory,
        priority=25,
    )
    return registry


def test_initializer_is_idempotent_and_injects_the_installed_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _BusAwareHandler()
    registry = _registry_with(lambda: handler)
    installed: list[InMemoryEventBus] = []
    monkeypatch.setattr(
        event_bus_initializer,
        "get_event_subscriber_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        EventBusInitializer,
        "_register_decision_execution_handlers",
        staticmethod(lambda _bus, _handlers: None),
    )
    monkeypatch.setattr(
        event_bus_initializer,
        "install_event_bus",
        installed.append,
    )
    monkeypatch.setattr(event_bus_initializer, "is_celery_available", lambda: False)
    initializer = EventBusInitializer()

    first = initializer.initialize()
    second = initializer.initialize()

    assert second is first
    assert installed == [first, first]
    assert handler.event_bus is first
    subscription = first.get_subscriptions(EventType.REGIME_CHANGED)[0]
    assert subscription.subscription_id == "registry:test_subscriber:regime_changed"
    assert subscription.priority == 25
    initializer.shutdown()


def test_initializer_fails_closed_when_subscriber_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_factory() -> EventHandler:
        raise RuntimeError("broken subscriber wiring")

    candidate = InMemoryEventBus()
    installed: list[InMemoryEventBus] = []
    monkeypatch.setattr(
        event_bus_initializer,
        "get_event_subscriber_registry",
        lambda: _registry_with(broken_factory),
    )
    monkeypatch.setattr(
        EventBusInitializer,
        "_create_event_bus",
        staticmethod(lambda: candidate),
    )
    monkeypatch.setattr(
        event_bus_initializer,
        "install_event_bus",
        installed.append,
    )
    initializer = EventBusInitializer()

    with pytest.raises(RuntimeError, match="broken subscriber wiring"):
        initializer.initialize()

    assert initializer.get_event_bus() is None
    assert initializer.get_handlers() == []
    assert installed == []
    assert candidate._executor_shutdown is True


def test_install_event_bus_is_the_domain_global_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "_global_event_bus", None)
    candidate = InMemoryEventBus()

    services.install_event_bus(candidate)

    assert services.get_event_bus() is candidate
    services.reset_event_bus()


def test_events_app_starts_after_all_subscriber_apps() -> None:
    installed_apps = list(settings.INSTALLED_APPS)

    assert installed_apps.index("apps.decision_rhythm") < installed_apps.index("apps.events")
    assert installed_apps.index("apps.alpha_trigger") < installed_apps.index("apps.events")
    assert installed_apps.index("apps.beta_gate") < installed_apps.index("apps.events")


def test_django_ready_bus_is_the_domain_global_bus() -> None:
    initialized_bus = event_bus_initializer.initialize_event_bus()

    assert services.get_event_bus() is initialized_bus
    subscription_ids = {
        subscription.subscription_id
        for subscription in initialized_bus.get_subscriptions(EventType.REGIME_CHANGED)
    }
    assert "registry:beta_gate:regime_changed" in subscription_ids


def test_events_app_ready_propagates_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.events.apps import EventsConfig

    def fail_initialization() -> None:
        raise RuntimeError("required handler unavailable")

    monkeypatch.setattr(
        "apps.events.application.initialize_event_bus",
        fail_initialization,
    )

    with pytest.raises(ImproperlyConfigured, match="Failed to initialize"):
        EventsConfig("apps.events", event_bus_initializer).ready()
