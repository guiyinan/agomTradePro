"""Component evidence for owner-scoped queued-run event replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from json import loads
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.domain.entities import TaskDomain, TaskStatus
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalRunContractError,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)
from apps.agent_runtime.infrastructure.models import AgentTaskModel
from apps.agent_runtime.infrastructure.terminal_agent_run_repository import (
    TerminalAgentRunRepository,
)
from apps.terminal.interface import queued_runtime_views

pytestmark = pytest.mark.django_db(transaction=True)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def owner(db):
    """Create the authenticated owner for one disposable run."""

    user_model = get_user_model()
    return user_model.objects.create_user(username=f"tar-events-owner-{uuid4().hex[:8]}")


@pytest.fixture
def task(owner):
    """Create an AgentTask bound to the event-stream owner."""

    return AgentTaskModel.objects.create(
        request_id=f"tar-events-task-{uuid4().hex[:20]}",
        task_domain=TaskDomain.RESEARCH.value,
        task_type="terminal_event_contract_test",
        status=TaskStatus.DRAFT.value,
        input_payload={"task_ref": "event-replay-test"},
        created_by=owner,
    )


@pytest.fixture
def repository() -> TerminalAgentRunRepository:
    """Build the real database-backed repository under test."""

    return TerminalAgentRunRepository()


def _request(*, owner_id: int, task_id: int, suffix: str) -> TerminalQueuedSubmissionRequest:
    """Build one valid queued-run admission request for a test run."""

    accepted_at = _NOW
    submission = TerminalRunSubmission(
        selector=TerminalRunSelector(
            run_id=f"run-events-{suffix}",
            task_id=task_id,
            actor_user_id=owner_id,
            client_request_id=f"request-events-{suffix}",
        ),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )
    return TerminalQueuedSubmissionRequest(
        submission=submission,
        message="must never be persisted in the event stream",
    )


def _running_run(
    repository: TerminalAgentRunRepository,
    *,
    owner_id: int,
    task_id: int,
    suffix: str,
) -> tuple[str, str]:
    """Admit and start one run so the worker lease may append events."""

    request = _request(owner_id=owner_id, task_id=task_id, suffix=suffix)
    run_id = request.submission.selector.run_id
    worker_id = f"worker-events-{suffix}"
    repository.submit(request)
    assert repository.claim(run_id=run_id, worker_id=worker_id, claimed_at=_NOW) is not None
    assert (
        repository.mark_started(
            run_id=run_id,
            worker_id=worker_id,
            started_at=_NOW + timedelta(seconds=1),
        )
        is not None
    )
    return run_id, worker_id


def _append(
    repository: TerminalAgentRunRepository,
    *,
    run_id: str,
    worker_id: str,
    event_type: str,
    data: dict[str, object],
    offset: int,
) -> None:
    """Append one safe event and assert the durable record was created."""

    event = repository.append_event(
        run_id=run_id,
        worker_id=worker_id,
        event_type=event_type,
        data=data,
        occurred_at=_NOW + timedelta(seconds=offset),
    )
    assert event is not None


def _enabled_settings():
    """Enable only the bounded queued-runtime route flags for a test."""

    return override_settings(
        TERMINAL_QUEUED_INTAKE_ENABLED=True,
        TERMINAL_QUEUED_WORKER_ENABLED=True,
        TERMINAL_RUNTIME_AUTHORIZED=True,
        TERMINAL_EMERGENCY_STOP=False,
    )


def test_repository_replays_bounded_ordered_events_after_cursor_and_terminal_state(
    repository,
    owner,
    task,
):
    """A reconnect cursor is monotonic, bounded, and includes terminal evidence."""

    run_id, worker_id = _running_run(
        repository,
        owner_id=owner.id,
        task_id=task.id,
        suffix="replay",
    )
    _append(
        repository,
        run_id=run_id,
        worker_id=worker_id,
        event_type="run.accepted",
        data={"stage": "accepted"},
        offset=2,
    )
    _append(
        repository,
        run_id=run_id,
        worker_id=worker_id,
        event_type="run.progress",
        data={"stage": "working", "percent": 50},
        offset=3,
    )
    _append(
        repository,
        run_id=run_id,
        worker_id=worker_id,
        event_type="run.completed",
        data={"stage": "completed", "result": {"count": 1}},
        offset=4,
    )
    assert (
        repository.mark_finished(
            run_id=run_id,
            worker_id=worker_id,
            status=TerminalRunStatus.COMPLETED,
            finished_at=_NOW + timedelta(seconds=5),
        )
        is not None
    )

    first_batch = repository.list_events(
        run_id=run_id,
        actor_user_id=owner.id,
        after_sequence=0,
        limit=2,
    )
    assert first_batch is not None
    assert [event.sequence for event in first_batch] == [1, 2]
    assert [event.event_type for event in first_batch] == ["run.accepted", "run.progress"]

    reconnect_batch = repository.list_events(
        run_id=run_id,
        actor_user_id=owner.id,
        after_sequence=first_batch[-1].sequence,
        limit=2,
    )
    assert reconnect_batch is not None
    assert [event.sequence for event in reconnect_batch] == [3]
    assert reconnect_batch[0].event_type == "run.completed"
    assert (
        repository.get_snapshot(run_id=run_id, actor_user_id=owner.id).status
        is TerminalRunStatus.COMPLETED
    )


def test_repository_event_replay_denies_foreign_owner(repository, owner, task):
    """An authenticated but different user cannot enumerate another run's events."""

    run_id, worker_id = _running_run(
        repository,
        owner_id=owner.id,
        task_id=task.id,
        suffix="owner-scope",
    )
    _append(
        repository,
        run_id=run_id,
        worker_id=worker_id,
        event_type="run.progress",
        data={"stage": "working"},
        offset=2,
    )
    other_user = get_user_model().objects.create_user(
        username=f"tar-events-other-{uuid4().hex[:8]}"
    )

    assert (
        repository.list_events(
            run_id=run_id,
            actor_user_id=other_user.id,
            after_sequence=0,
            limit=100,
        )
        is None
    )


def test_events_view_reconnects_from_last_event_id_and_returns_404_for_foreign_owner(
    monkeypatch,
    repository,
    owner,
    task,
):
    """The HTTP replay route binds its cursor and result to the authenticated owner."""

    run_id, worker_id = _running_run(
        repository,
        owner_id=owner.id,
        task_id=task.id,
        suffix="view-replay",
    )
    for offset, stage in ((2, "accepted"), (3, "working"), (4, "completed")):
        _append(
            repository,
            run_id=run_id,
            worker_id=worker_id,
            event_type=f"run.{stage}",
            data={"stage": stage},
            offset=offset,
        )
    monkeypatch.setattr(
        queued_runtime_views,
        "get_terminal_agent_run_repository",
        lambda: repository,
    )
    factory = APIRequestFactory()
    request = factory.get(
        f"/api/terminal/runs/{run_id}/events/",
        HTTP_LAST_EVENT_ID="1",
        HTTP_ACCEPT="application/json",
    )
    force_authenticate(request, user=owner)

    with _enabled_settings():
        response = queued_runtime_views.TerminalQueuedRunEventsView.as_view()(
            request,
            run_id=run_id,
        )

    assert response.status_code == 200
    assert response.data["run_id"] == run_id
    assert [event["sequence"] for event in response.data["events"]] == [2, 3]
    assert all("must never be persisted" not in str(event) for event in response.data["events"])

    foreign_request = factory.get(
        f"/api/terminal/runs/{run_id}/events/",
        HTTP_ACCEPT="application/json",
    )
    other_user = get_user_model().objects.create_user(
        username=f"tar-events-view-other-{uuid4().hex[:8]}"
    )
    force_authenticate(foreign_request, user=other_user)
    with _enabled_settings():
        foreign_response = queued_runtime_views.TerminalQueuedRunEventsView.as_view()(
            foreign_request,
            run_id=run_id,
        )
    assert foreign_response.status_code == 404


def test_events_view_emits_safe_json_sse_frames_and_rejects_sensitive_event_data(
    monkeypatch,
    repository,
    owner,
    task,
):
    """SSE frames preserve safe JSON while the repository rejects prompt fields."""

    run_id, worker_id = _running_run(
        repository,
        owner_id=owner.id,
        task_id=task.id,
        suffix="sse",
    )
    _append(
        repository,
        run_id=run_id,
        worker_id=worker_id,
        event_type="run.progress",
        data={"message": "ready", "nested": {"count": 2}},
        offset=2,
    )
    with pytest.raises(TerminalRunContractError, match="sensitive field"):
        repository.append_event(
            run_id=run_id,
            worker_id=worker_id,
            event_type="run.secret",
            data={"prompt": "do not emit this"},
            occurred_at=_NOW + timedelta(seconds=3),
        )

    monkeypatch.setattr(
        queued_runtime_views,
        "get_terminal_agent_run_repository",
        lambda: repository,
    )
    request = APIRequestFactory().get(
        f"/api/terminal/runs/{run_id}/events/",
        HTTP_ACCEPT="text/event-stream",
    )
    force_authenticate(request, user=owner)
    with _enabled_settings():
        response = queued_runtime_views.TerminalQueuedRunEventsView.as_view()(
            request,
            run_id=run_id,
        )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/event-stream")
    body = b"".join(response.streaming_content).decode("utf-8")
    assert body.startswith("id: 1\nevent: run.progress\n")
    data_line = next(line for line in body.splitlines() if line.startswith("data: "))
    assert loads(data_line.removeprefix("data: ")) == {
        "message": "ready",
        "nested": {"count": 2},
    }
    assert "do not emit this" not in body
