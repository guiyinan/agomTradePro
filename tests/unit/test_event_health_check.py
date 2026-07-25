"""Operational event health regressions."""

from __future__ import annotations

import pytest

from apps.events.application import health_check
from apps.events.application import tasks as event_tasks
from apps.events.domain.entities import (
    DomainEvent,
    EventHandler,
    EventMetrics,
    EventSubscription,
    EventType,
)
from apps.events.domain.services import InMemoryEventBus


class _NamedHandler(EventHandler):
    def __init__(self, handler_id: str) -> None:
        self._handler_id = handler_id

    def can_handle(self, event_type: EventType) -> bool:
        return True

    def handle(self, event: DomainEvent) -> None:
        return None

    def get_handler_id(self) -> str:
        return self._handler_id


class _HealthyEventStore:
    @staticmethod
    def get_metrics() -> EventMetrics:
        return EventMetrics(total_events=0, events_by_type={})


def _critical_bus() -> InMemoryEventBus:
    bus = InMemoryEventBus()
    for event_type, handler_id in (
        (EventType.DECISION_APPROVED, "events.DecisionApprovedHandler"),
        (EventType.DECISION_EXECUTED, "events.DecisionExecutedHandler"),
        (
            EventType.DECISION_EXECUTION_FAILED,
            "events.DecisionExecutionFailedHandler",
        ),
    ):
        bus.subscribe(
            EventSubscription(
                subscription_id=f"test:{event_type.value}",
                event_type=event_type,
                handler=_NamedHandler(handler_id),
            )
        )
    return bus


def test_idle_event_bus_with_required_handlers_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = _critical_bus()
    monkeypatch.setattr(health_check, "get_event_bus", lambda: bus)
    monkeypatch.setattr(health_check, "get_event_store", _HealthyEventStore)

    report = health_check.EventBusHealthChecker().check_all()

    assert report.overall_status == "OK"
    assert report.is_healthy() is True
    assert all(check.status == "OK" for check in report.checks)
    bus.stop()


def test_missing_critical_handlers_are_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = InMemoryEventBus()
    monkeypatch.setattr(health_check, "get_event_bus", lambda: bus)
    monkeypatch.setattr(health_check, "get_event_store", _HealthyEventStore)

    report = health_check.EventBusHealthChecker().check_all()

    assert report.overall_status == "ERROR"
    statuses = {check.component: check.status for check in report.checks}
    assert statuses["handler_registration"] == "ERROR"
    assert statuses["critical_handlers"] == "ERROR"
    bus.stop()


def test_periodic_health_task_treats_idle_bus_as_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = _critical_bus()
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: bus)

    result = event_tasks.event_bus_health_check.run()

    assert result["success"] is True
    assert result["is_healthy"] is True
    assert result["metrics"]["failure_rate"] == 0.0
    bus.stop()


def test_periodic_health_task_rejects_zero_subscribers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = InMemoryEventBus()
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: bus)

    result = event_tasks.event_bus_health_check.run()

    assert result["success"] is True
    assert result["is_healthy"] is False
    bus.stop()
