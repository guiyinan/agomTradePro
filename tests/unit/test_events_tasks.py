"""Focused side-effect tests for event publication tasks."""

from apps.events.application import tasks as event_tasks


class _FailingEventStore:
    @staticmethod
    def append(event):
        return False


class _RecordingEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_publish_event_async_does_not_notify_when_persistence_fails(monkeypatch):
    event_bus = _RecordingEventBus()
    monkeypatch.setattr(event_tasks, "get_event_store", lambda: _FailingEventStore())
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: event_bus)
    monkeypatch.setattr(event_tasks.publish_event_async, "max_retries", 0)

    result = event_tasks.publish_event_async.run(
        event_type="regime_changed",
        payload={"new_regime": "Overheat"},
        event_id="event-task-failure-001",
        occurred_at="2026-07-12T12:00:00+00:00",
    )

    assert result["success"] is False
    assert "persistence failed" in result["error"].lower()
    assert event_bus.events == []


def test_publish_batch_events_async_does_not_notify_failed_appends(monkeypatch):
    event_bus = _RecordingEventBus()
    monkeypatch.setattr(event_tasks, "get_event_store", lambda: _FailingEventStore())
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: event_bus)

    result = event_tasks.publish_batch_events_async.run(
        [
            {
                "event_type": "regime_changed",
                "payload": {"new_regime": "Overheat"},
                "event_id": "event-batch-failure-001",
            }
        ]
    )

    assert result["success_count"] == 0
    assert result["failed_count"] == 1
    assert "persistence failed" in result["errors"][0]["error"].lower()
    assert event_bus.events == []
