"""Application task contracts for event publication and maintenance."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.events.application import tasks
from apps.events.domain.entities import DomainEvent, EventHandler, EventType


class ReplayHandler(EventHandler):
    """Importable replay target used by the dynamic task boundary."""

    def can_handle(self, event_type: EventType) -> bool:
        return event_type == EventType.REGIME_CHANGED

    def handle(self, event: DomainEvent) -> None:
        assert event.event_type == EventType.REGIME_CHANGED


def test_publish_single_and_batch_events_persist_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_store = MagicMock()
    event_store.get_by_id.return_value = None
    event_store.append.side_effect = [True, True, False]
    event_bus = MagicMock()
    monkeypatch.setattr(tasks, "get_event_store", lambda: event_store)
    monkeypatch.setattr(tasks, "get_event_bus", lambda: event_bus)

    response = tasks.publish_event_async.run(
        EventType.REGIME_CHANGED.value,
        {"regime": "Recovery"},
        {"source": "test"},
        "event-1",
        "2026-07-24T00:00:00Z",
        "correlation-1",
        "causation-1",
    )
    assert response["success"] is True
    assert response["event_id"] == "event-1"
    published = event_bus.publish.call_args.args[0]
    assert published.metadata["correlation_id"] == "correlation-1"
    assert published.metadata["causation_id"] == "causation-1"

    batch = tasks.publish_batch_events_async.run(
        [
            {
                "event_type": EventType.SIGNAL_CREATED.value,
                "payload": {"signal": 1},
            },
            {
                "event_type": EventType.SIGNAL_CREATED.value,
                "payload": {"signal": 2},
            },
        ]
    )
    assert batch["success_count"] == 1
    assert batch["failed_count"] == 1
    assert len(batch["errors"]) == 1


def test_replay_events_parses_dates_and_dynamic_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay = MagicMock()
    replay.replay_to.return_value = 4
    monkeypatch.setattr(tasks, "get_replay_handler", lambda: replay)

    response = tasks.replay_events_async.run(
        event_type=EventType.REGIME_CHANGED.value,
        since="2026-07-01T00:00:00Z",
        until=None,
        limit=50,
        target_handler_class=("tests.unit.events.test_t5_application_task_contracts.ReplayHandler"),
    )

    assert response["success"] is True
    assert response["events_replayed"] == 4
    kwargs = replay.replay_to.call_args.kwargs
    assert isinstance(kwargs["subscriber"], EventHandler)
    assert kwargs["subscriber"].__class__.__name__ == "ReplayHandler"
    assert kwargs["since"].tzinfo is UTC
    assert kwargs["until"] is None


@pytest.mark.parametrize(
    ("deleted_count", "expected_message"),
    [(0, "No old events to delete"), (3, None)],
)
def test_cleanup_old_events_handles_noop_and_success(
    monkeypatch: pytest.MonkeyPatch,
    deleted_count: int,
    expected_message: str | None,
) -> None:
    store = SimpleNamespace(
        cleanup_old_events=lambda **_kwargs: deleted_count,
    )
    monkeypatch.setattr(tasks, "get_event_store", lambda: store)
    response = tasks.cleanup_old_events.run(older_than_days=14, batch_size=50)
    assert response["success"] is True
    assert response["deleted_count"] == deleted_count
    assert response.get("message") == expected_message


def test_cleanup_tasks_return_failures_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing_store = SimpleNamespace(
        cleanup_old_events=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("event cleanup failed")
        ),
        cleanup_old_snapshots=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("snapshot cleanup failed")
        ),
    )
    monkeypatch.setattr(tasks, "get_event_store", lambda: failing_store)
    monkeypatch.setattr(tasks, "get_snapshot_store", lambda: failing_store)
    with pytest.raises(RuntimeError, match="event cleanup failed"):
        tasks.cleanup_old_events.run()
    with pytest.raises(RuntimeError, match="snapshot cleanup failed"):
        tasks.cleanup_old_snapshots.run()


def test_cleanup_snapshots_returns_deleted_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    store.cleanup_old_snapshots.return_value = 5
    monkeypatch.setattr(tasks, "get_snapshot_store", lambda: store)
    response = tasks.cleanup_old_snapshots.run(older_than_days=90, keep_latest=10)
    assert response["success"] is True
    assert response["deleted_count"] == 5


def _metrics(*, failed: int = 1, processed: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        total_published=25,
        total_processed=processed,
        total_failed=failed,
        total_subscribers=3,
        avg_processing_time_ms=25.0,
        last_event_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_metrics_and_health_tasks_cover_success_zero_total_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = MagicMock()
    bus.get_metrics.return_value = _metrics()
    store = SimpleNamespace(
        get_metrics=lambda: SimpleNamespace(
            total_events=100,
            events_by_type={"regime_changed": 20},
        )
    )
    monkeypatch.setattr(tasks, "get_event_bus", lambda: bus)
    monkeypatch.setattr(tasks, "get_event_store", lambda: store)

    collected = tasks.collect_event_metrics.run()
    assert collected["success"] is True
    assert collected["metrics"]["memory"]["success_rate"] == pytest.approx(20 / 21 * 100)
    assert collected["metrics"]["memory"]["last_event_at"].startswith("2026-07-24")
    assert tasks.event_bus_health_check.run()["is_healthy"] is True

    bus.get_metrics.return_value = _metrics(failed=0, processed=0)
    zero = tasks.collect_event_metrics.run()
    assert zero["metrics"]["memory"]["success_rate"] == 0

    bus.get_metrics.side_effect = RuntimeError("metrics unavailable")
    with pytest.raises(RuntimeError, match="metrics unavailable"):
        tasks.collect_event_metrics.run()
    with pytest.raises(RuntimeError, match="metrics unavailable"):
        tasks.event_bus_health_check.run()
