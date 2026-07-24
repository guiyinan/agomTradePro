"""Decision Rhythm event subscriber wiring regressions."""

import pytest

from apps.decision_rhythm.application import subscribers
from apps.events.domain.entities import EventHandler, EventType
from apps.events.domain.registry import EventSubscriberRegistry


def test_approved_event_keeps_all_three_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registry deduplication must not overwrite quota or cooldown handlers."""
    registry = EventSubscriberRegistry()
    monkeypatch.setattr(
        subscribers,
        "get_event_subscriber_registry",
        lambda: registry,
    )

    subscribers.register_subscribers()

    approved = registry.get_subscribers(EventType.DECISION_APPROVED)
    assert [item.module_name for item in approved] == [
        "decision_rhythm.quota_monitor",
        "decision_rhythm.cooldown",
        "decision_rhythm.core",
    ]
    assert [item.priority for item in approved] == [50, 55, 60]


def test_handler_factories_return_event_handlers() -> None:
    """Every advertised factory must create the EventHandler contract."""
    factories = subscribers.get_handler_factories()

    assert set(factories) == {
        EventType.DECISION_APPROVED,
        EventType.DECISION_REJECTED,
        EventType.ALPHA_TRIGGER_FIRED,
        EventType.SIGNAL_TRIGGERED,
    }
    assert all(isinstance(factory(), EventHandler) for factory in factories.values())


class _FailingRegistry:
    def register(self, **kwargs: object) -> None:
        raise RuntimeError("registry unavailable")


def test_registration_failure_is_not_silenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup must see subscription failures instead of running partially wired."""
    monkeypatch.setattr(
        subscribers,
        "get_event_subscriber_registry",
        lambda: _FailingRegistry(),
    )

    with pytest.raises(RuntimeError, match="registry unavailable"):
        subscribers.register_subscribers()
