"""Durable failed-event claim, transition, retry, and retention contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.events.application.event_retry import EventRetryManager
from apps.events.domain.entities import DomainEvent, EventType
from apps.events.infrastructure.models import FailedEventModel
from apps.events.infrastructure.repositories import FailedEventRepository


def _event(event_id: str) -> DomainEvent:
    return DomainEvent(
        event_id=event_id,
        event_type=EventType.DECISION_EXECUTED,
        occurred_at=datetime.now(UTC),
        payload={"request_id": "request-1"},
        metadata={"trace_id": "trace-1"},
    )


@pytest.mark.django_db
def test_failed_event_claim_is_exclusive_and_success_is_conditional() -> None:
    """Only one worker can claim a due row and only its claim can become success."""

    repository = FailedEventRepository()
    event_db_id = repository.save(
        _event("event-claim"),
        handler_id="events.handler",
        error_message="temporary",
        error_traceback=None,
        max_retries=3,
    )

    assert [item["id"] for item in repository.find_pending_events(10, None)] == [event_db_id]
    assert repository.update_status(
        event_db_id,
        FailedEventModel.RETRYING,
        timezone.now(),
    )
    assert not repository.update_status(
        event_db_id,
        FailedEventModel.RETRYING,
        timezone.now(),
    )
    assert repository.mark_success(event_db_id)
    assert not repository.mark_success(event_db_id)
    assert repository.get_by_id(event_db_id)["status"] == FailedEventModel.SUCCESS


@pytest.mark.django_db
def test_retry_manager_does_not_execute_handler_for_stale_claim() -> None:
    """A stale DTO cannot execute the handler after another retry has completed."""

    repository = FailedEventRepository()
    manager = EventRetryManager(failed_event_repo=repository)
    failed = manager.record_failure(
        _event("event-manager-claim"),
        handler_id="events.handler",
        error=RuntimeError("temporary"),
    )
    handled: list[str] = []

    assert manager.retry_event(failed, lambda event: handled.append(event.event_id))
    assert not manager.retry_event(failed, lambda event: handled.append(event.event_id))
    assert handled == ["event-manager-claim"]


@pytest.mark.django_db
def test_retry_exhaustion_uses_locked_persisted_counters() -> None:
    """Repository truth exhausts a one-attempt row even if the caller hint is stale."""

    repository = FailedEventRepository()
    event_db_id = repository.save(
        _event("event-exhaust"),
        handler_id="events.handler",
        error_message="temporary",
        error_traceback=None,
        max_retries=1,
    )
    assert repository.update_status(
        event_db_id,
        FailedEventModel.RETRYING,
        timezone.now(),
    )

    assert repository.increment_retry_count(
        event_db_id,
        error_message="still failing",
        next_retry_at=timezone.now() + timedelta(minutes=10),
        is_exhausted=False,
    )

    stored = repository.get_by_id(event_db_id)
    assert stored is not None
    assert stored["retry_count"] == 1
    assert stored["status"] == FailedEventModel.EXHAUSTED
    assert stored["next_retry_at"] is None


@pytest.mark.django_db
def test_failed_event_retention_rejects_unsafe_days_and_deletes_only_terminal_rows() -> None:
    """Negative/zero retention cannot widen deletion and pending rows are preserved."""

    repository = FailedEventRepository()
    success_id = repository.save(
        _event("event-old-success"),
        handler_id="events.handler",
        error_message="temporary",
        error_traceback=None,
        max_retries=3,
    )
    pending_id = repository.save(
        _event("event-old-pending"),
        handler_id="events.handler",
        error_message="temporary",
        error_traceback=None,
        max_retries=3,
    )
    assert repository.update_status(success_id, FailedEventModel.RETRYING, timezone.now())
    assert repository.mark_success(success_id)
    old_timestamp = timezone.now() - timedelta(days=45)
    FailedEventModel._default_manager.filter(pk__in=[success_id, pending_id]).update(
        updated_at=old_timestamp
    )

    for invalid_days in (0, -1, True):
        with pytest.raises(ValueError, match="days"):
            repository.cleanup_old_events(invalid_days)
    assert FailedEventModel._default_manager.count() == 2

    assert repository.cleanup_old_events(30) == 1
    assert not FailedEventModel._default_manager.filter(pk=success_id).exists()
    assert FailedEventModel._default_manager.filter(pk=pending_id).exists()


@pytest.mark.django_db
def test_failed_event_repository_rejects_invalid_query_and_timestamp_inputs() -> None:
    """Invalid direct calls fail before changing a pending row."""

    repository = FailedEventRepository()
    event_db_id = repository.save(
        _event("event-validation"),
        handler_id="events.handler",
        error_message="temporary",
        error_traceback=None,
        max_retries=3,
    )

    with pytest.raises(ValueError, match="limit"):
        repository.find_pending_events(0, None)
    with pytest.raises(ValueError, match="handler_id"):
        repository.find_pending_events(1, "   ")
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.update_status(
            event_db_id,
            FailedEventModel.RETRYING,
            datetime.now(),
        )
    assert repository.get_by_id(event_db_id)["status"] == FailedEventModel.PENDING
