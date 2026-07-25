"""Focused side-effect tests for event publication tasks."""

from datetime import UTC, datetime

from apps.events.application import tasks as event_tasks
from apps.events.domain.entities import EventType, create_event


class _FailingEventStore:
    @staticmethod
    def get_by_id(event_id):
        return None

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
    assert result["success"] is False
    assert "persistence failed" in result["errors"][0]["error"].lower()
    assert event_bus.events == []


def test_replay_events_async_requires_an_explicit_handler(monkeypatch):
    monkeypatch.setattr(event_tasks.replay_events_async, "max_retries", 0)

    result = event_tasks.replay_events_async.run()

    assert result["success"] is False
    assert result["error"] == "Replay requires an explicit target_handler_class"


def test_publish_event_async_rejects_naive_occurred_at(monkeypatch):
    event_bus = _RecordingEventBus()
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: event_bus)

    result = event_tasks.publish_event_async.run(
        event_type="regime_changed",
        payload={"new_regime": "Overheat"},
        event_id="event-naive-time-001",
        occurred_at="2026-07-25T12:00:00",
    )

    assert result["success"] is False
    assert "timezone offset" in result["error"]
    assert event_bus.events == []


class _ExistingEventStore:
    def __init__(self, existing):
        self.existing = existing
        self.appended = []

    def get_by_id(self, event_id):
        assert event_id == self.existing.event_id
        return self.existing

    def append(self, event):
        self.appended.append(event)
        return True


def test_publish_event_async_resumes_delivery_after_event_was_already_stored(monkeypatch):
    existing = create_event(
        EventType.REGIME_CHANGED,
        {"new_regime": "Overheat"},
        event_id="event-resume-001",
        occurred_at=datetime(2026, 7, 25, 4, 0, tzinfo=UTC),
    )
    event_store = _ExistingEventStore(existing)
    event_bus = _RecordingEventBus()
    monkeypatch.setattr(event_tasks, "get_event_store", lambda: event_store)
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: event_bus)

    result = event_tasks.publish_event_async.run(
        event_type="regime_changed",
        payload={"new_regime": "Overheat"},
        event_id="event-resume-001",
        occurred_at="2026-07-25T12:00:00+08:00",
    )

    assert result["success"] is True
    assert event_store.appended == []
    assert len(event_bus.events) == 1


def test_publish_event_async_rejects_conflicting_existing_event(monkeypatch):
    existing = create_event(
        EventType.REGIME_CHANGED,
        {"new_regime": "Recovery"},
        event_id="event-conflict-001",
        occurred_at=datetime(2026, 7, 25, 4, 0, tzinfo=UTC),
    )
    event_store = _ExistingEventStore(existing)
    event_bus = _RecordingEventBus()
    monkeypatch.setattr(event_tasks, "get_event_store", lambda: event_store)
    monkeypatch.setattr(event_tasks, "get_event_bus", lambda: event_bus)

    result = event_tasks.publish_event_async.run(
        event_type="regime_changed",
        payload={"new_regime": "Overheat"},
        event_id="event-conflict-001",
        occurred_at="2026-07-25T12:00:00+08:00",
    )

    assert result["success"] is False
    assert "conflicts with a different event" in result["error"]
    assert event_bus.events == []


class _BrokenCleanupStore:
    @staticmethod
    def cleanup_old_events(*, older_than_days, batch_size):
        raise RuntimeError("database unavailable")


def test_cleanup_old_events_reports_exhausted_infrastructure_failure(monkeypatch):
    monkeypatch.setattr(event_tasks, "get_event_store", _BrokenCleanupStore)
    monkeypatch.setattr(event_tasks.cleanup_old_events, "max_retries", 0)

    result = event_tasks.cleanup_old_events.run()

    assert result["success"] is False
    assert result["retries"] == 0
    assert result["error"] == "database unavailable"


def test_cleanup_old_events_rejects_invalid_batch_size_without_retry(monkeypatch):
    monkeypatch.setattr(event_tasks.cleanup_old_events, "max_retries", 3)

    result = event_tasks.cleanup_old_events.run(batch_size=0)

    assert result["success"] is False
    assert result["error"] == "batch_size must be greater than zero"
    assert "retries" not in result
