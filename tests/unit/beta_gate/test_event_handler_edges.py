"""Beta Gate event-handler publication and registration contracts."""

from __future__ import annotations

from apps.beta_gate.application import subscribers
from apps.beta_gate.application.handlers import BetaGateEventHandler, GateInvalidationHandler
from apps.events.domain.entities import EventType, create_event


class _Bus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_beta_gate_handler_routes_supported_events_and_publishes_reason() -> None:
    """Supported macro events publish one auditable Beta Gate evaluation event."""
    bus = _Bus()
    handler = BetaGateEventHandler(
        universe_builder=object(),
        config_selector=object(),
        event_bus=bus,
    )
    assert handler.can_handle(EventType.REGIME_CHANGED)
    assert handler.can_handle(EventType.POLICY_LEVEL_CHANGED)
    assert not handler.can_handle(EventType.SIGNAL_CREATED)
    assert handler.get_handler_id() == "beta_gate.BetaGateEventHandler"

    handler.handle(
        create_event(
            EventType.REGIME_CHANGED,
            {"old_regime": "Deflation", "new_regime": "Recovery", "confidence": 0.8},
        )
    )
    handler.handle(
        create_event(
            EventType.POLICY_LEVEL_CHANGED,
            {"old_level": 1, "new_level": 2},
        )
    )
    handler.handle(
        create_event(
            EventType.REGIME_CONFIDENCE_LOW,
            {"confidence": 0.2, "threshold": 0.3},
        )
    )
    reasons = [event.payload["reason"] for event in bus.events]
    assert reasons == ["regime_changed", "policy_changed", "confidence_low"]

    invalidation = GateInvalidationHandler(config_selector=object())
    assert invalidation.can_handle(EventType.BETA_GATE_BLOCKED)
    invalidation.handle(
        create_event(
            EventType.BETA_GATE_BLOCKED,
            {"asset_code": "000001.SZ", "blocking_reason": "policy"},
        )
    )
    assert invalidation.get_handler_id() == "beta_gate.GateInvalidationHandler"


def test_subscriber_registration_publishes_both_factories(monkeypatch) -> None:
    """Subscriber registry receives the two declared event mappings."""
    calls: list[dict[str, object]] = []
    registry = type("Registry", (), {"register": lambda self, **kwargs: calls.append(kwargs)})()
    monkeypatch.setattr(subscribers, "get_event_subscriber_registry", lambda: registry)
    subscribers.register_subscribers()
    assert [call["event_type"] for call in calls] == [
        EventType.REGIME_CHANGED,
        EventType.POLICY_LEVEL_CHANGED,
    ]
    assert set(subscribers.get_handler_factories()) == {
        EventType.REGIME_CHANGED,
        EventType.POLICY_LEVEL_CHANGED,
    }
