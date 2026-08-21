"""Contract tests for the dedicated Terminal Agent Celery task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.agent_runtime.application import tasks
from apps.agent_runtime.application.terminal_agent import TerminalAgentEventDTO
from apps.agent_runtime.application.terminal_agent_run_runtime import TerminalAgentWorkerInput
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def _claimed() -> TerminalAgentRunContract:
    """Build one claimed worker input identity for task tests."""

    accepted = TerminalRunSubmission(
        selector=TerminalRunSelector(
            run_id="run-task-contract-0001",
            task_id=17,
            actor_user_id=7,
            client_request_id="request-task-contract-0001",
        ),
        runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
        request_digest="a" * 64,
        accepted_at=NOW,
        deadline_at=NOW + timedelta(minutes=2),
    )
    return TerminalAgentRunContract(
        submission=accepted,
        dispatch_status=TerminalRunStatus.CLAIMED,
        claimed_by="worker-test",
        claimed_at=NOW,
        heartbeat_at=NOW,
    )


class _FakeRepository:
    """Small lifecycle fake that records task state transitions."""

    def __init__(self, claimed: TerminalAgentRunContract | None) -> None:
        self.claimed = claimed
        self.finished: list[dict[str, object]] = []

    def claim(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Return the configured first-winner claim."""

        return self.claimed

    def mark_started(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Record a started transition without touching a database."""

        return self.claimed

    def get_worker_input(self, **_kwargs: object) -> TerminalAgentWorkerInput | None:
        """Return one safe task payload for the worker."""

        return TerminalAgentWorkerInput(
            run_id="run-task-contract-0001",
            task_id=17,
            actor_user_id=7,
            message="health check",
            session_id="session-task-contract",
            username="operator",
            user_role="admin",
            user_is_admin=True,
            mcp_enabled=False,
            provider_ref=None,
            model=None,
            context={},
        )

    def heartbeat(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Keep the fake lease alive."""

        return self.claimed

    def append_event(self, **_kwargs: object) -> object:
        """Accept one normalized event."""

        return object()

    def get_for_owner(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Return the current fake run state."""

        return self.claimed

    def transition(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Accept a non-terminal transition."""

        return self.claimed

    def mark_finished(self, **kwargs: object) -> TerminalAgentRunContract | None:
        """Record terminal outcome for assertions."""

        self.finished.append(kwargs)
        return self.claimed

    def reap_stale(self, **_kwargs: object) -> int:
        """Return one explicit orphan transition for reaper tests."""

        return 1


class _FakeService:
    """Deterministic stream used to prove the task does not inline-admit."""

    def stream_chat(self, _request: object):
        """Yield one final response event."""

        yield TerminalAgentEventDTO(
            event_type="final",
            data={"reply": "ok", "metadata": {"source": "test"}},
        )


def test_execute_terminal_agent_run_blocks_before_claim_when_worker_disabled(settings):
    """A disabled worker cannot claim or execute a queued run."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = False

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result == {"outcome": "blocked", "reason_code": "queued_worker_disabled"}


def test_execute_terminal_agent_run_returns_noop_for_lost_first_winner(monkeypatch, settings):
    """A duplicate delivery with no claim is a stable no-op."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(None)
    monkeypatch.setattr(tasks, "_repo", lambda: repository)

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result["outcome"] == "noop"
    assert result["reason_code"] == "run_not_queued"


def test_execute_terminal_agent_run_marks_success_without_broker_payload(monkeypatch, settings):
    """A claimed run streams events, checkpoints, and stores only bounded output."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(tasks, "get_terminal_agent_service", lambda: _FakeService())

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result == {
        "outcome": "success",
        "status": "completed",
        "run_id": "run-task-contract-0001",
    }
    assert repository.finished[0]["status"] is TerminalRunStatus.COMPLETED
    assert repository.finished[0]["result_ref"] == "run:run-task-contract-0001:result"


def test_execute_terminal_agent_run_marks_input_failure(monkeypatch, settings):
    """Malformed task payloads become a redacted durable failure."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(repository, "get_worker_input", lambda **_kwargs: None)

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result["outcome"] == "failed"
    assert repository.finished[0]["error_code"] == "terminal_agent_execution_failed"


def test_reap_stale_terminal_agent_runs_blocks_when_worker_disabled(settings):
    """The reaper remains dormant until the reviewed worker flag is enabled."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = False

    result = tasks.reap_stale_terminal_agent_runs.run()

    assert result == {"outcome": "blocked", "reason_code": "queued_worker_disabled"}


def test_reap_stale_terminal_agent_runs_returns_reaped_count(monkeypatch, settings):
    """The enabled reaper reports durable orphan transitions without payloads."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    settings.TERMINAL_AGENT_ORPHAN_AFTER_SECONDS = 90
    repository = _FakeRepository(None)
    monkeypatch.setattr(tasks, "_repo", lambda: repository)

    result = tasks.reap_stale_terminal_agent_runs.run()

    assert result == {"outcome": "success", "reaped": 1}
