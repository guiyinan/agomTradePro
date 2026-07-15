"""Controlled replay preview, execution, and idempotency orchestration."""

from datetime import UTC, datetime

import pytest

from apps.events.application.replay_registry import ReplayTarget, ReplayTargetRegistry
from apps.events.application.replay_service import (
    ReplayConflictError,
    ReplayInProgressError,
    ReplayService,
)
from apps.events.domain.entities import DomainEvent, EventHandler, EventType
from apps.events.domain.replay import ReplayFilter, ReplayRunReservation


class _Store:
    def __init__(self, events):
        self.events = events

    def get_events(self, **kwargs):
        return self.events[: kwargs["limit"]]


class _Handler(EventHandler):
    def __init__(self, fail_id=None):
        self.calls = []
        self.fail_id = fail_id

    def can_handle(self, event_type):
        return event_type == EventType.DECISION_APPROVED

    def handle(self, event):
        self.calls.append(event.event_id)
        if event.event_id == self.fail_id:
            raise RuntimeError("secret database detail")


class _Runs:
    def __init__(self, state="reserved", stored_result=None):
        self.state = state
        self.stored_result = stored_result
        self.reservations = []
        self.completed = []

    def reserve(self, **kwargs):
        self.reservations.append(kwargs)
        return ReplayRunReservation(self.state, 9, self.stored_result)

    def complete(self, run_id, result):
        self.completed.append((run_id, result))

    def fail(self, run_id, message):
        raise AssertionError("not expected")


def _event(event_id: str, event_type=EventType.DECISION_APPROVED):
    return DomainEvent(event_id, event_type, datetime.now(UTC), {}, {})


def _service(handler, runs, events=None, enabled=True):
    registry = ReplayTargetRegistry(
        [
            ReplayTarget(
                "decision.approved",
                (EventType.DECISION_APPROVED,),
                "write decision state",
                lambda: handler,
            )
        ]
    )
    return ReplayService(registry, _Store(events or []), runs, enabled=enabled)


def test_preview_has_no_handler_invocation_or_run_write() -> None:
    handler = _Handler()
    runs = _Runs()
    service = _service(handler, runs, [_event("1"), _event("2")])

    preview = service.preview(
        "decision.approved",
        ReplayFilter(EventType.DECISION_APPROVED, limit=10),
    )

    assert preview["candidate_count"] == 2
    assert preview["side_effect_description"] == "write decision state"
    assert [item["event_id"] for item in preview["event_sample"]] == ["1", "2"]
    assert handler.calls == []
    assert runs.reservations == []


def test_commit_records_success_skip_and_sanitized_failure() -> None:
    handler = _Handler(fail_id="2")
    runs = _Runs()
    events = [_event("1"), _event("2"), _event("3", EventType.SYSTEM_ERROR)]
    service = _service(handler, runs, events)

    summary = service.commit(
        "decision.approved",
        ReplayFilter(EventType.DECISION_APPROVED, limit=10),
        requester_id=4,
        idempotency_key="idem",
    )

    assert summary["outcome"] == "partial"
    assert summary["succeeded"] == 1
    assert summary["skipped"] == 1
    assert summary["failed"] == 1
    assert "secret database detail" not in summary["failures"][0]["message"]
    assert len(runs.completed) == 1


@pytest.mark.parametrize(
    ("state", "error"),
    [("conflict", ReplayConflictError), ("in_progress", ReplayInProgressError)],
)
def test_commit_does_not_invoke_handler_for_unavailable_reservation(state, error) -> None:
    handler = _Handler()
    service = _service(handler, _Runs(state=state), [_event("1")])

    with pytest.raises(error):
        service.commit(
            "decision.approved",
            ReplayFilter(EventType.DECISION_APPROVED, limit=10),
            requester_id=4,
            idempotency_key="idem",
        )
    assert handler.calls == []


def test_commit_returns_stored_result_for_idempotent_replay() -> None:
    stored = {"outcome": "completed", "attempted": 1}
    handler = _Handler()
    service = _service(handler, _Runs(state="replay", stored_result=stored))

    assert service.commit(
        "decision.approved",
        ReplayFilter(EventType.DECISION_APPROVED, limit=10),
        requester_id=4,
        idempotency_key="idem",
    ) == {**stored, "idempotent_replay": True, "run_id": 9}
    assert handler.calls == []
