"""Pure TAR-01 API and SSE wire-contract tests."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_agent_run_api_contract import (
    TerminalRunAcceptedResponse,
    TerminalRunApiContractError,
    TerminalRunApiRoute,
    TerminalRunCancelResponse,
    TerminalRunEvent,
    TerminalRunEventReplay,
    TerminalRunEventReplayQuery,
    TerminalRunStatusResponse,
    terminal_run_route,
    validate_terminal_run_event_replay,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import TerminalRunStatus

RUN_ID = "run-20260818-0001"
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _urls() -> tuple[str, str, str]:
    """Build the canonical URLs for the fixture run."""

    return (
        terminal_run_route(TerminalRunApiRoute.DETAIL, RUN_ID),
        terminal_run_route(TerminalRunApiRoute.EVENTS, RUN_ID),
        terminal_run_route(TerminalRunApiRoute.CANCEL, RUN_ID),
    )


def test_routes_freeze_async_api_names_and_path_substitution() -> None:
    """The future API has one canonical create, status, event, cancel and queue path."""

    assert terminal_run_route(TerminalRunApiRoute.CREATE) == "/api/terminal/runs/"
    assert terminal_run_route(TerminalRunApiRoute.QUEUE) == "/api/terminal/runs/queue/"
    assert _urls() == (
        "/api/terminal/runs/run-20260818-0001/",
        "/api/terminal/runs/run-20260818-0001/events/",
        "/api/terminal/runs/run-20260818-0001/cancel/",
    )


@pytest.mark.parametrize(
    "route,run_id",
    [
        (TerminalRunApiRoute.DETAIL, None),
        (TerminalRunApiRoute.CREATE, RUN_ID),
        (TerminalRunApiRoute.DETAIL, "bad/run-id"),
    ],
)
def test_route_builder_rejects_ambiguous_run_scope(
    route: TerminalRunApiRoute,
    run_id: str | None,
) -> None:
    """Route generation cannot omit or inject an owner-scoped run identifier."""

    with pytest.raises(TerminalRunApiContractError):
        terminal_run_route(route, run_id)


def test_accepted_response_has_exact_202_payload_shape() -> None:
    """Creation returns IDs and links only, never prompt, provider or credential material."""

    status_url, events_url, cancel_url = _urls()
    response = TerminalRunAcceptedResponse(
        run_id=RUN_ID,
        task_id=17,
        status=TerminalRunStatus.QUEUED,
        submitted_at=NOW,
        status_url=status_url,
        events_url=events_url,
        cancel_url=cancel_url,
    )

    assert response.to_payload() == {
        "run_id": RUN_ID,
        "task_id": 17,
        "status": "queued",
        "submitted_at": NOW.isoformat(),
        "status_url": status_url,
        "events_url": events_url,
        "cancel_url": cancel_url,
    }


def test_accepted_response_rejects_running_status_or_naive_clock() -> None:
    """A create response cannot claim work started or publish a naive timestamp."""

    status_url, events_url, cancel_url = _urls()
    with pytest.raises(TerminalRunApiContractError, match="invalid status"):
        TerminalRunAcceptedResponse(
            run_id=RUN_ID,
            task_id=17,
            status=TerminalRunStatus.RUNNING,
            submitted_at=NOW,
            status_url=status_url,
            events_url=events_url,
            cancel_url=cancel_url,
        )
    with pytest.raises(TerminalRunApiContractError, match="timezone-aware"):
        TerminalRunAcceptedResponse(
            run_id=RUN_ID,
            task_id=17,
            status=TerminalRunStatus.ACCEPTED,
            submitted_at=NOW.replace(tzinfo=None),
            status_url=status_url,
            events_url=events_url,
            cancel_url=cancel_url,
        )


def test_status_envelopes_reject_string_status_substitution() -> None:
    """Wire responses must carry the frozen enum, not a look-alike string."""

    status_url, events_url, cancel_url = _urls()
    with pytest.raises(TerminalRunApiContractError, match="invalid status"):
        TerminalRunStatusResponse(
            run_id=RUN_ID,
            status="queued",  # type: ignore[arg-type]
            updated_at=NOW,
            status_url=status_url,
            events_url=events_url,
            cancel_url=cancel_url,
        )
    with pytest.raises(TerminalRunApiContractError, match="invalid status"):
        TerminalRunCancelResponse(
            run_id=RUN_ID,
            status="cancelled",  # type: ignore[arg-type]
            cancel_requested_at=NOW,
        )


def test_status_and_cancel_payloads_preserve_stable_machine_fields() -> None:
    """Polling and cancellation expose stable codes without queue implementation details."""

    status_url, events_url, cancel_url = _urls()
    status = TerminalRunStatusResponse(
        run_id=RUN_ID,
        status=TerminalRunStatus.FAILED,
        updated_at=NOW,
        status_url=status_url,
        events_url=events_url,
        cancel_url=cancel_url,
        error_code="MODEL_TIMEOUT",
        result_ref="result-0001",
    )
    cancel = TerminalRunCancelResponse(
        run_id=RUN_ID,
        status=TerminalRunStatus.CANCEL_REQUESTED,
        cancel_requested_at=NOW + timedelta(seconds=2),
    )

    assert status.to_payload()["error_code"] == "MODEL_TIMEOUT"
    assert status.to_payload()["result_ref"] == "result-0001"
    assert cancel.to_payload()["status"] == "cancel_requested"


def test_event_rejects_sensitive_data_and_preserves_replay_envelope() -> None:
    """SSE events may carry safe progress data but never prompts or credentials."""

    event = TerminalRunEvent(
        event_id="event-0001",
        event_type="status",
        run_id=RUN_ID,
        occurred_at=NOW,
        data={"status": "running", "attempt": 1},
    )
    assert event.to_payload() == {
        "event_id": "event-0001",
        "event_type": "status",
        "run_id": RUN_ID,
        "occurred_at": NOW.isoformat(),
        "data": {"status": "running", "attempt": 1},
    }

    with pytest.raises(TerminalRunApiContractError):
        TerminalRunEvent(
            event_id="event-0002",
            event_type="tool_progress",
            run_id=RUN_ID,
            occurred_at=NOW,
            data={"prompt": "do not persist this"},
        )


def test_event_replay_enforces_owner_scope_cursor_order_and_bound() -> None:
    """Replay batches bind one owner/run and cannot skip, duplicate or overrun a cursor."""

    query = TerminalRunEventReplayQuery(
        run_id=RUN_ID,
        actor_user_id=7,
        after_sequence=2,
        limit=2,
    )
    events = (
        TerminalRunEventReplay(
            event_id="event-0003",
            event_type="status",
            run_id=RUN_ID,
            occurred_at=NOW,
            sequence=3,
            data={"status": "running"},
        ),
        TerminalRunEventReplay(
            event_id="event-0004",
            event_type="completed",
            run_id=RUN_ID,
            occurred_at=NOW,
            sequence=4,
            data={"status": "completed"},
        ),
    )

    assert validate_terminal_run_event_replay(query, events) == events
    assert events[-1].to_payload()["sequence"] == 4

    with pytest.raises(TerminalRunApiContractError, match="run_id"):
        validate_terminal_run_event_replay(
            query,
            (
                TerminalRunEventReplay(
                    event_id="event-other-run",
                    event_type="status",
                    run_id="run-20260818-0002",
                    occurred_at=NOW,
                    sequence=3,
                    data={},
                ),
            ),
        )
    with pytest.raises(TerminalRunApiContractError, match="strictly increasing"):
        validate_terminal_run_event_replay(query, (events[0], events[0]))
    with pytest.raises(TerminalRunApiContractError, match="limit"):
        validate_terminal_run_event_replay(query, events + (events[1],))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actor_user_id": True},
        {"after_sequence": -1},
        {"limit": 0},
        {"limit": 101},
    ],
)
def test_event_replay_query_rejects_ambiguous_cursor_controls(kwargs: dict[str, object]) -> None:
    """Cursor controls never coerce bools, negatives or unbounded batches."""

    with pytest.raises(TerminalRunApiContractError):
        query_kwargs: dict[str, object] = {"actor_user_id": 7}
        query_kwargs.update(kwargs)
        TerminalRunEventReplayQuery(run_id=RUN_ID, **query_kwargs)  # type: ignore[arg-type]


def test_event_replay_rejects_sequence_and_sensitive_payload_substitution() -> None:
    """Replay envelopes reject zero/boolean sequences and secret-bearing data."""

    with pytest.raises(TerminalRunApiContractError):
        TerminalRunEventReplay(
            event_id="event-zero",
            event_type="status",
            run_id=RUN_ID,
            occurred_at=NOW,
            sequence=0,
            data={},
        )
    with pytest.raises(TerminalRunApiContractError):
        TerminalRunEventReplay(
            event_id="event-bool",
            event_type="status",
            run_id=RUN_ID,
            occurred_at=NOW,
            sequence=True,  # type: ignore[arg-type]
            data={},
        )
    with pytest.raises(TerminalRunApiContractError):
        TerminalRunEventReplay(
            event_id="event-secret",
            event_type="status",
            run_id=RUN_ID,
            occurred_at=NOW,
            sequence=1,
            data={"authorization": "redacted"},
        )


def test_api_contract_is_free_of_framework_and_inline_agent_dependencies() -> None:
    """The wire contract stays pure until an Interface/composition root binds it."""

    source_path = Path("apps/agent_runtime/application/terminal_agent_run_api_contract.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all(not name.startswith("django") for name in imported_names)
    assert all("infrastructure" not in name for name in imported_names)
    assert all("celery" not in name.casefold() for name in imported_names)
    assert "OpenAIAgentsTerminalService" not in source
    assert ".objects" not in source
