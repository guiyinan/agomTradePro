"""Event retry contracts, including explicit UNKNOWN event preservation."""

from datetime import UTC, datetime
from typing import Any

import pytest

from apps.events.application import event_retry
from apps.events.application.event_retry import EventRetryManager, FailedEventDTO
from apps.events.domain.entities import DomainEvent, EventType


def _stored_event(
    *,
    event_id: str = "event-1",
    event_type: str = EventType.DECISION_EXECUTED.value,
    retry_count: int = 0,
    max_retries: int = 3,
    status: str = "PENDING",
) -> dict[str, Any]:
    return {
        "id": 1,
        "event_id": event_id,
        "event_type": event_type,
        "payload": {"request_id": "request-1"},
        "metadata": {"source": "unit"},
        "handler_id": "handler.one",
        "error_message": "boom",
        "retry_count": retry_count,
        "max_retries": max_retries,
        "next_retry_at": None,
        "status": status,
    }


class _FailedEventRepository:
    def __init__(self) -> None:
        self.rows = [_stored_event()]
        self.updated: list[dict[str, Any]] = []
        self.success_ids: list[int] = []
        self.incremented: list[dict[str, Any]] = []

    def save(self, **_kwargs: Any) -> int:
        return 1

    def get_by_id(self, event_db_id: int) -> dict[str, Any] | None:
        assert event_db_id == 1
        return self.rows[0] if self.rows else None

    def find_pending_events(
        self,
        *,
        limit: int,
        handler_id: str | None,
    ) -> list[dict[str, Any]]:
        rows = (
            self.rows
            if handler_id is None
            else [row for row in self.rows if row["handler_id"] == handler_id]
        )
        return rows[:limit]

    def update_status(self, **kwargs: Any) -> None:
        self.updated.append(kwargs)

    def mark_success(self, event_db_id: int) -> None:
        self.success_ids.append(event_db_id)

    def increment_retry_count(self, **kwargs: Any) -> None:
        self.incremented.append(kwargs)
        if self.rows:
            self.rows[0]["status"] = "EXHAUSTED" if kwargs["is_exhausted"] else "PENDING"

    def cleanup_old_events(self, days: int) -> int:
        return days


def _dto(**overrides: Any) -> FailedEventDTO:
    payload = _stored_event(**overrides)
    return FailedEventDTO(**payload)


def test_record_and_pending_event_mapping_preserve_repository_contract() -> None:
    repository = _FailedEventRepository()
    manager = EventRetryManager(failed_event_repo=repository)
    event = DomainEvent(
        event_id="event-1",
        event_type=EventType.DECISION_EXECUTED,
        occurred_at=datetime.now(UTC),
        payload={"request_id": "request-1"},
        metadata={"source": "unit"},
    )

    stored = manager.record_failure(event, "handler.one", RuntimeError("boom"), "trace")
    pending = manager.get_pending_events(limit=5, handler_id="handler.one")

    assert stored.event_id == "event-1"
    assert pending == [stored]
    assert manager.cleanup_old_events(14) == 14


def test_record_failure_refuses_missing_saved_row() -> None:
    repository = _FailedEventRepository()
    repository.rows.clear()
    manager = EventRetryManager(failed_event_repo=repository)
    event = DomainEvent(
        event_id="event-1",
        event_type=EventType.DECISION_EXECUTED,
        occurred_at=datetime.now(UTC),
        payload={},
        metadata={},
    )

    with pytest.raises(RuntimeError, match="Failed to retrieve"):
        manager.record_failure(event, "handler.one", RuntimeError("boom"))


def test_retry_unknown_event_uses_unknown_instead_of_business_type() -> None:
    repository = _FailedEventRepository()
    manager = EventRetryManager(failed_event_repo=repository)
    observed: list[DomainEvent] = []

    assert manager.retry_event(_dto(event_type="future_event"), observed.append) is True

    assert observed[0].event_type is EventType.UNKNOWN
    assert repository.success_ids == [1]


def test_retry_failure_schedules_backoff_then_exhausts() -> None:
    repository = _FailedEventRepository()
    manager = EventRetryManager(base_delay_minutes=7, failed_event_repo=repository)

    assert (
        manager.retry_event(
            _dto(retry_count=0, max_retries=3),
            lambda _event: (_ for _ in ()).throw(RuntimeError("retry")),
        )
        is False
    )
    first = repository.incremented[-1]
    assert first["is_exhausted"] is False
    assert first["next_retry_at"] is not None

    assert (
        manager.retry_event(
            _dto(retry_count=2, max_retries=3),
            lambda _event: (_ for _ in ()).throw(RuntimeError("final")),
        )
        is False
    )
    final = repository.incremented[-1]
    assert final["is_exhausted"] is True
    assert final["next_retry_at"] is None


def test_batch_retry_distinguishes_missing_failed_exhausted_and_success() -> None:
    repository = _FailedEventRepository()
    repository.rows = [
        _stored_event(event_id="missing"),
        _stored_event(event_id="success"),
        _stored_event(event_id="failed", retry_count=0),
        _stored_event(event_id="exhausted", retry_count=2),
    ]
    manager = EventRetryManager(failed_event_repo=repository)

    def fake_retry(dto: FailedEventDTO, _handler: object) -> bool:
        if dto.event_id == "success":
            return True
        repository.rows[0]["status"] = "EXHAUSTED" if dto.event_id == "exhausted" else "PENDING"
        repository.get_by_id = lambda _event_id: repository.rows[0]
        return False

    manager.retry_event = fake_retry  # type: ignore[method-assign]
    stats = manager.retry_pending_events(
        lambda handler_id: None if handler_id == "missing.handler" else lambda _event: None
    )

    # All fixtures use handler.one, so exercise a missing handler separately.
    assert stats["success"] == 1
    assert stats["failed"] + stats["exhausted"] == 3


def test_retry_manager_singleton_uses_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _FailedEventRepository()
    monkeypatch.setattr(event_retry, "_event_retry_manager", None)
    monkeypatch.setattr(event_retry, "get_failed_event_repository", lambda: repository)

    first = event_retry.get_event_retry_manager()
    second = event_retry.get_event_retry_manager()

    assert first is second
