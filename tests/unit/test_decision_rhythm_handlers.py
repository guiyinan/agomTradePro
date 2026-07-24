"""Behavioral regressions for Decision Rhythm event handlers."""

from datetime import UTC, datetime

from apps.decision_rhythm.application.handlers import (
    CooldownEventHandler,
    QuotaMonitorHandler,
)
from apps.decision_rhythm.domain.entities import CooldownPeriod, QuotaPeriod
from apps.decision_rhythm.domain.services import CooldownManager
from apps.events.domain.entities import DomainEvent, EventType, create_event


class RecordingEventBus:
    """Capture published domain events for assertions."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


class StubQuotaManager:
    """Expose the current QuotaManager status-key contract."""

    def __init__(self, *, remaining: int, total: int) -> None:
        self.remaining = remaining
        self.total = total

    def get_quota_status(self, period: QuotaPeriod) -> dict[str, object]:
        return {
            "period": period.value,
            "remaining_decisions": self.remaining,
            "max_decisions": self.total,
        }


def test_quota_monitor_uses_domain_status_keys() -> None:
    """Low remaining quota should publish the dedicated warning event."""

    event_bus = RecordingEventBus()
    handler = QuotaMonitorHandler(
        quota_manager=StubQuotaManager(remaining=1, total=10),
        event_bus=event_bus,
    )

    handler.handle(create_event(EventType.DECISION_APPROVED, {}))

    assert len(event_bus.events) == len(QuotaPeriod)
    assert {event.event_type for event in event_bus.events} == {EventType.QUOTA_WARNING}


def test_signal_cooldown_uses_existing_domain_manager_api() -> None:
    """An active cooldown should publish a rejection without attribute errors."""

    manager = CooldownManager()
    manager.cooldowns["000001.SZ"] = CooldownPeriod(
        asset_code="000001.SZ",
        last_decision_at=datetime.now(UTC),
        min_decision_interval_hours=24,
    )
    event_bus = RecordingEventBus()
    handler = CooldownEventHandler(manager, event_bus)

    handler.handle(
        create_event(
            EventType.SIGNAL_TRIGGERED,
            {"asset_code": "000001.SZ"},
        )
    )

    assert len(event_bus.events) == 1
    assert event_bus.events[0].event_type == EventType.DECISION_REJECTED
