"""Event subscriber registry contract and concurrency regressions."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from apps.events.domain.entities import DomainEvent, EventHandler, EventType
from apps.events.domain.registry import (
    EventSubscriberRegistry,
    SubscriberInfo,
    get_event_subscriber_registry,
    reset_event_subscriber_registry,
)


class _Handler(EventHandler):
    def can_handle(self, event_type: EventType) -> bool:
        return True

    def handle(self, event: DomainEvent) -> None:
        return None


def _handler_factory() -> EventHandler:
    return _Handler()


@pytest.mark.parametrize("module_name", ["", " leading", "bad/name", "x" * 129])
def test_registry_rejects_invalid_module_names(module_name: str) -> None:
    registry = EventSubscriberRegistry()

    with pytest.raises(ValueError, match="event_subscriber_module_name_invalid"):
        registry.register(
            module_name=module_name,
            event_type=EventType.REGIME_CHANGED,
            handler_factory=_handler_factory,
        )


@pytest.mark.parametrize("priority", [True, -10_001, 10_001])
def test_registry_rejects_invalid_priority(priority: object) -> None:
    registry = EventSubscriberRegistry()

    with pytest.raises(ValueError, match="event_subscriber_priority_invalid"):
        registry.register(
            module_name="valid.module",
            event_type=EventType.REGIME_CHANGED,
            handler_factory=_handler_factory,
            priority=priority,
        )


def test_registry_returns_frozen_defensive_snapshots() -> None:
    registry = EventSubscriberRegistry()
    registry.register(
        module_name="valid.module",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=_handler_factory,
        priority=10,
    )

    snapshot = registry.get_subscribers(EventType.REGIME_CHANGED)
    snapshot.clear()

    current = registry.get_subscribers(EventType.REGIME_CHANGED)
    assert len(current) == 1
    with pytest.raises(FrozenInstanceError):
        current[0].priority = 999


def test_registry_duplicate_registration_atomically_replaces_and_resorts() -> None:
    registry = EventSubscriberRegistry()
    registry.register(
        module_name="module.slow",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=_handler_factory,
        priority=100,
    )
    registry.register(
        module_name="module.fast",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=_handler_factory,
        priority=20,
    )
    registry.register(
        module_name="module.slow",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=_handler_factory,
        priority=10,
        description="updated",
    )

    subscribers = registry.get_subscribers(EventType.REGIME_CHANGED)

    assert [item.module_name for item in subscribers] == [
        "module.slow",
        "module.fast",
    ]
    assert subscribers[0].priority == 10
    assert subscribers[0].description == "updated"


def test_registry_concurrent_registration_keeps_every_unique_subscriber() -> None:
    registry = EventSubscriberRegistry()

    def register(index: int) -> None:
        registry.register(
            module_name=f"worker.{index}",
            event_type=EventType.SIGNAL_CREATED,
            handler_factory=_handler_factory,
            priority=index,
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(register, range(100)))

    subscribers = registry.get_subscribers(EventType.SIGNAL_CREATED)
    assert len(subscribers) == 100
    assert [item.priority for item in subscribers] == list(range(100))


def test_global_registry_singleton_is_stable_under_concurrent_first_access() -> None:
    reset_event_subscriber_registry()
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            registry_ids = list(
                executor.map(
                    lambda _index: id(get_event_subscriber_registry()),
                    range(100),
                )
            )
        assert len(set(registry_ids)) == 1
    finally:
        reset_event_subscriber_registry()


def test_subscriber_info_rejects_non_callable_factory_and_control_description() -> None:
    with pytest.raises(TypeError, match="event_subscriber_factory_invalid"):
        SubscriberInfo(
            module_name="valid.module",
            event_type=EventType.REGIME_CHANGED,
            handler_factory=None,
        )
    with pytest.raises(ValueError, match="event_subscriber_description_invalid"):
        SubscriberInfo(
            module_name="valid.module",
            event_type=EventType.REGIME_CHANGED,
            handler_factory=_handler_factory,
            description="bad\nvalue",
        )
