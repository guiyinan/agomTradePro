"""
Tests for apps.events.domain.services — InMemoryEventBus, event_handler decorator, factory functions

Pure-Python tests: no Django, pandas, or numpy imports.
Uses factory helpers from tests.factories.domain_factories.
"""

from datetime import datetime, timezone

import pytest

from apps.events.domain.entities import (
    DomainEvent,
    EventBusConfig,
    EventHandler,
    EventMetrics,
    EventSubscription,
    EventType,
    create_event,
    create_subscription,
)
from apps.events.domain.services import (
    InMemoryEventBus,
    reset_event_bus,
)
from tests.factories.domain_factories import (
    make_domain_event,
    make_event_bus_config,
)


# ============================================================
# Helpers
# ============================================================


class _RecordingHandler(EventHandler):
    """Simple handler that records received events for assertions."""

    def __init__(self, handler_id: str = "test_handler") -> None:
        self._handler_id = handler_id
        self.received: list[DomainEvent] = []

    def can_handle(self, event_type: EventType) -> bool:
        return True

    def handle(self, event: DomainEvent) -> None:
        self.received.append(event)

    def get_handler_id(self) -> str:
        return self._handler_id


class _FailingHandler(EventHandler):
    """Handler that always raises an exception."""

    def can_handle(self, event_type: EventType) -> bool:
        return True

    def handle(self, event: DomainEvent) -> None:
        raise RuntimeError("deliberate failure")

    def get_handler_id(self) -> str:
        return "failing_handler"


def _make_subscription(
    event_type: EventType = EventType.REGIME_CHANGED,
    handler: EventHandler | None = None,
    subscription_id: str = "sub-001",
    priority: int = 100,
    **kwargs,
) -> EventSubscription:
    return EventSubscription(
        subscription_id=subscription_id,
        event_type=event_type,
        handler=handler or _RecordingHandler(),
        is_active=True,
        priority=priority,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _reset_global_bus():
    """Reset the global event bus before each test to avoid cross-contamination."""
    reset_event_bus()
    yield
    reset_event_bus()


# ============================================================
# InMemoryEventBus.subscribe / unsubscribe
# ============================================================


class TestSubscribeUnsubscribe:
    """Tests for subscribe and unsubscribe behaviour."""

    def test_subscribe_adds_handler(self) -> None:
        """After subscribing, the bus should have one subscriber."""
        bus = InMemoryEventBus()
        bus.subscribe(_make_subscription())

        assert bus.get_subscription_count() == 1

    def test_subscribe_duplicate_id_raises(self) -> None:
        """Subscribing with the same ID twice raises ValueError."""
        bus = InMemoryEventBus()
        bus.subscribe(_make_subscription(subscription_id="dup"))

        with pytest.raises(ValueError, match="already exists"):
            bus.subscribe(_make_subscription(subscription_id="dup"))

    def test_unsubscribe_existing(self) -> None:
        """Unsubscribing an existing subscription returns True and removes it."""
        bus = InMemoryEventBus()
        bus.subscribe(_make_subscription(subscription_id="sub-x"))

        result = bus.unsubscribe("sub-x")

        assert result is True
        assert bus.get_subscription_count() == 0

    def test_unsubscribe_nonexistent(self) -> None:
        """Unsubscribing a non-existent ID returns False."""
        bus = InMemoryEventBus()
        assert bus.unsubscribe("no-such-id") is False

    def test_subscribe_priority_ordering(self) -> None:
        """Subscriptions are sorted by priority (lower number = higher priority)."""
        bus = InMemoryEventBus()
        bus.subscribe(
            _make_subscription(subscription_id="low-priority", priority=200)
        )
        bus.subscribe(
            _make_subscription(subscription_id="high-priority", priority=10)
        )

        subs = bus.get_subscriptions(EventType.REGIME_CHANGED)
        assert subs[0].subscription_id == "high-priority"
        assert subs[1].subscription_id == "low-priority"


# ============================================================
# InMemoryEventBus.publish
# ============================================================


class TestPublish:
    """Tests for publish behaviour."""

    def test_publish_delivers_to_subscriber(self) -> None:
        """Published event is delivered to the subscribed handler."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))

        event = make_domain_event()
        bus.publish(event)

        assert len(handler.received) == 1
        assert handler.received[0].event_id == event.event_id

    def test_publish_no_subscribers(self) -> None:
        """Publishing to no subscribers does not raise."""
        bus = InMemoryEventBus()
        event = make_domain_event(event_type=EventType.SIGNAL_CREATED)

        # Should not raise
        bus.publish(event)

    def test_publish_updates_metrics_total_published(self) -> None:
        """Each publish increments total_published."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))

        bus.publish(make_domain_event(event_id="e1"))
        bus.publish(make_domain_event(event_id="e2"))

        metrics = bus.get_metrics()
        assert metrics.total_published == 2

    def test_publish_when_stopped_is_ignored(self) -> None:
        """Events published after stop() are ignored."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))
        bus.stop()

        bus.publish(make_domain_event())

        assert len(handler.received) == 0

    def test_publish_failing_handler_increments_failed(self) -> None:
        """A failing handler increments total_failed."""
        bus = InMemoryEventBus(EventBusConfig(retry_failed_events=False))
        bus.subscribe(
            _make_subscription(handler=_FailingHandler(), subscription_id="fail-sub")
        )

        bus.publish(make_domain_event())

        metrics = bus.get_metrics()
        assert metrics.total_failed >= 1

    def test_publish_with_filter_criteria(self) -> None:
        """Handler with filter_criteria only receives matching events."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(
            _make_subscription(
                handler=handler,
                subscription_id="filtered",
                filter_criteria={"source": "official"},
            )
        )

        # Non-matching event
        bus.publish(make_domain_event(payload={"source": "unofficial"}))
        assert len(handler.received) == 0

        # Matching event
        bus.publish(make_domain_event(event_id="e2", payload={"source": "official"}))
        assert len(handler.received) == 1


# ============================================================
# InMemoryEventBus.publish_batch
# ============================================================


class TestPublishBatch:
    """Tests for publish_batch behaviour."""

    def test_publish_batch_delivers_all(self) -> None:
        """All events in a batch are delivered."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))

        events = [make_domain_event(event_id=f"batch-{i}") for i in range(5)]
        bus.publish_batch(events)

        assert len(handler.received) == 5

    def test_publish_batch_empty_list(self) -> None:
        """Empty batch does nothing."""
        bus = InMemoryEventBus()
        bus.publish_batch([])
        assert bus.get_metrics().total_published == 0


# ============================================================
# InMemoryEventBus.get_metrics
# ============================================================


class TestGetMetrics:
    """Tests for get_metrics."""

    def test_initial_metrics_zeroed(self) -> None:
        """Fresh bus has all-zero metrics."""
        bus = InMemoryEventBus()
        metrics = bus.get_metrics()

        assert metrics.total_published == 0
        assert metrics.total_processed == 0
        assert metrics.total_failed == 0
        assert metrics.total_subscribers == 0

    def test_metrics_reflect_subscribe_count(self) -> None:
        """Subscribing and unsubscribing updates total_subscribers."""
        bus = InMemoryEventBus()
        bus.subscribe(_make_subscription(subscription_id="s1"))
        bus.subscribe(_make_subscription(subscription_id="s2"))

        assert bus.get_metrics().total_subscribers == 2

        bus.unsubscribe("s1")
        assert bus.get_metrics().total_subscribers == 1

    def test_metrics_is_deep_copy(self) -> None:
        """Returned metrics object is a deep copy."""
        bus = InMemoryEventBus()
        m1 = bus.get_metrics()
        m1.total_published = 999

        m2 = bus.get_metrics()
        assert m2.total_published == 0


# ============================================================
# InMemoryEventBus.replay_events
# ============================================================


class TestReplayEvents:
    """Tests for replay_events."""

    def test_replay_all_events(self) -> None:
        """Replaying re-delivers all queued events."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))

        bus.publish(make_domain_event(event_id="r1"))
        bus.publish(make_domain_event(event_id="r2"))
        handler.received.clear()

        count = bus.replay_events()

        assert count == 2
        assert len(handler.received) == 2

    def test_replay_filtered_by_type(self) -> None:
        """Replaying with an event_type filter only replays matching events."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))
        bus.subscribe(
            _make_subscription(
                subscription_id="sig-sub",
                event_type=EventType.SIGNAL_CREATED,
                handler=handler,
            )
        )

        bus.publish(make_domain_event(event_id="r1", event_type=EventType.REGIME_CHANGED))
        bus.publish(
            make_domain_event(
                event_id="r2",
                event_type=EventType.SIGNAL_CREATED,
                payload={"signal": "test"},
            )
        )
        handler.received.clear()

        count = bus.replay_events(event_type=EventType.SIGNAL_CREATED)

        assert count == 1

    def test_replay_empty_queue(self) -> None:
        """Replaying with no events returns 0."""
        bus = InMemoryEventBus()
        assert bus.replay_events() == 0


# ============================================================
# InMemoryEventBus.clear
# ============================================================


class TestClear:
    """Tests for clear."""

    def test_clear_resets_everything(self) -> None:
        """Clear removes all subscriptions, events, and resets metrics."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))
        bus.publish(make_domain_event())

        bus.clear()

        assert bus.get_subscription_count() == 0
        assert bus.get_metrics().total_published == 0
        assert bus.get_metrics().total_subscribers == 0


# ============================================================
# InMemoryEventBus max_queue_size
# ============================================================


class TestMaxQueueSize:
    """Tests for max_queue_size enforcement."""

    def test_queue_evicts_oldest_when_full(self) -> None:
        """When queue exceeds max size, oldest events are evicted."""
        config = make_event_bus_config(max_queue_size=3)
        bus = InMemoryEventBus(config)

        for i in range(5):
            bus.publish(make_domain_event(event_id=f"e{i}"))

        # Replay should only have the last 3 events
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler, subscription_id="late"))
        count = bus.replay_events()
        assert count == 3


# ============================================================
# Factory functions: create_event, create_subscription
# ============================================================


class TestFactoryFunctions:
    """Tests for create_event and create_subscription convenience functions."""

    def test_create_event_generates_id(self) -> None:
        """create_event auto-generates an event_id."""
        event = create_event(EventType.REGIME_CHANGED, {"key": "val"})
        assert event.event_id is not None
        assert len(event.event_id) > 0

    def test_create_event_custom_id(self) -> None:
        """create_event respects a custom event_id."""
        event = create_event(
            EventType.REGIME_CHANGED, {"key": "val"}, event_id="custom-id"
        )
        assert event.event_id == "custom-id"

    def test_create_event_timezone_aware(self) -> None:
        """create_event produces a timezone-aware occurred_at."""
        event = create_event(EventType.REGIME_CHANGED, {})
        assert event.occurred_at.tzinfo is not None

    def test_create_subscription_generates_id(self) -> None:
        """create_subscription auto-generates a subscription_id."""
        handler = _RecordingHandler()
        sub = create_subscription(EventType.REGIME_CHANGED, handler)
        assert sub.subscription_id is not None
        assert len(sub.subscription_id) > 0

    def test_create_subscription_sets_priority(self) -> None:
        """create_subscription respects custom priority."""
        handler = _RecordingHandler()
        sub = create_subscription(EventType.REGIME_CHANGED, handler, priority=5)
        assert sub.priority == 5


# ============================================================
# event_handler decorator
# ============================================================


class TestEventHandlerDecorator:
    """Tests for the @event_handler decorator."""

    def test_decorator_registers_and_delivers(self) -> None:
        """The decorator registers the function and it receives published events."""
        from apps.events.domain.services import event_handler, get_event_bus

        received_events: list[DomainEvent] = []

        @event_handler(EventType.POLICY_LEVEL_CHANGED)
        def on_policy_change(event: DomainEvent) -> None:
            received_events.append(event)

        bus = get_event_bus()
        bus.publish(
            create_event(EventType.POLICY_LEVEL_CHANGED, {"level": "high"})
        )

        assert len(received_events) == 1
        assert received_events[0].payload["level"] == "high"


# ============================================================
# InMemoryEventBus.stop / start
# ============================================================


class TestStopStart:
    """Tests for stop and start lifecycle."""

    def test_start_after_stop_resumes(self) -> None:
        """Calling start() after stop() allows events to be processed again."""
        bus = InMemoryEventBus()
        handler = _RecordingHandler()
        bus.subscribe(_make_subscription(handler=handler))

        bus.stop()
        bus.publish(make_domain_event(event_id="ignored"))
        assert len(handler.received) == 0

        bus.start()
        bus.publish(make_domain_event(event_id="delivered"))
        assert len(handler.received) == 1
