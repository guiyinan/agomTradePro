"""Contract tests for the dedicated Terminal Agent Celery task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.agent_runtime.application import tasks
from apps.agent_runtime.application.terminal_agent import TerminalAgentEventDTO
from apps.agent_runtime.application.terminal_agent_run_runtime import TerminalAgentWorkerInput
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentBrokerEnvelope,
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
        self.started = claimed
        self.heartbeat_result = claimed
        self.append_result: object | None = object()
        self.finished_result = claimed
        self.worker_ids: list[str] = []
        self.dispatch_candidates: tuple[TerminalAgentBrokerEnvelope, ...] = ()

    def claim(self, **kwargs: object) -> TerminalAgentRunContract | None:
        """Return the configured first-winner claim."""

        worker_id = kwargs.get("worker_id")
        if isinstance(worker_id, str):
            self.worker_ids.append(worker_id)
        return self.claimed

    def mark_started(self, **kwargs: object) -> TerminalAgentRunContract | None:
        """Record a started transition without touching a database."""

        worker_id = kwargs.get("worker_id")
        if isinstance(worker_id, str):
            self.worker_ids.append(worker_id)
        return self.started

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

    def heartbeat(self, **kwargs: object) -> TerminalAgentRunContract | None:
        """Keep the fake lease alive."""

        worker_id = kwargs.get("worker_id")
        if isinstance(worker_id, str):
            self.worker_ids.append(worker_id)
        return self.heartbeat_result

    def append_event(self, **kwargs: object) -> object | None:
        """Accept one normalized event."""

        worker_id = kwargs.get("worker_id")
        if isinstance(worker_id, str):
            self.worker_ids.append(worker_id)
        return self.append_result

    def get_for_owner(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Return the current fake run state."""

        return self.claimed

    def transition(self, **_kwargs: object) -> TerminalAgentRunContract | None:
        """Accept a non-terminal transition."""

        return self.claimed

    def mark_finished(self, **kwargs: object) -> TerminalAgentRunContract | None:
        """Record terminal outcome for assertions."""

        self.finished.append(kwargs)
        worker_id = kwargs.get("worker_id")
        if isinstance(worker_id, str):
            self.worker_ids.append(worker_id)
        return self.finished_result

    def reap_stale(self, **_kwargs: object) -> int:
        """Return one explicit orphan transition for reaper tests."""

        return 1

    def list_queued_for_dispatch(
        self,
        **_kwargs: object,
    ) -> tuple[TerminalAgentBrokerEnvelope, ...]:
        """Return the configured durable IDs for reconciliation tests."""

        return self.dispatch_candidates


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


def test_execute_terminal_agent_run_blocks_before_claim_when_emergency_stop_is_on(
    monkeypatch, settings
):
    """Emergency stop prevents a dispatched task from claiming new work."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    settings.TERMINAL_EMERGENCY_STOP = True
    monkeypatch.setattr(
        tasks,
        "_repo",
        lambda: pytest.fail("emergency stop must block before repository claim"),
    )

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result == {"outcome": "blocked", "reason_code": "submissions_paused"}


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
    assert len(set(repository.worker_ids)) == 1


def test_execute_terminal_agent_run_uses_a_new_worker_identity_per_delivery() -> None:
    """Delivery identities are bounded and not shared by prefork invocations."""

    first = tasks._new_worker_id()
    second = tasks._new_worker_id()

    assert first != second
    assert len(first) <= 128
    assert len(second) <= 128


def test_execute_terminal_agent_run_stops_when_start_lease_is_lost(monkeypatch, settings):
    """A lost claim checkpoint cannot start the Agent service or write failure output."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    repository.started = None
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(
        tasks,
        "get_terminal_agent_service",
        lambda: pytest.fail("lease loss must stop before composing the service"),
    )

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result == {
        "outcome": "blocked",
        "reason_code": "worker_lease_lost",
        "run_id": "run-task-contract-0001",
    }
    assert repository.finished == []


def test_execute_terminal_agent_run_stops_when_heartbeat_lease_is_lost(monkeypatch, settings):
    """A heartbeat miss prevents the current stream event and terminal result."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    repository.heartbeat_result = None
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(tasks, "get_terminal_agent_service", lambda: _FakeService())

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result["reason_code"] == "worker_lease_lost"
    assert repository.finished == []


def test_execute_terminal_agent_run_stops_when_event_lease_is_lost(monkeypatch, settings):
    """A failed event checkpoint cannot be followed by a terminal result."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    repository.append_result = None
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(tasks, "get_terminal_agent_service", lambda: _FakeService())

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result["reason_code"] == "worker_lease_lost"
    assert repository.finished == []


def test_execute_terminal_agent_run_reports_lost_finish_lease(monkeypatch, settings):
    """A final checkpoint miss is blocked instead of claiming durable success."""

    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(_claimed())
    repository.finished_result = None
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(tasks, "get_terminal_agent_service", lambda: _FakeService())

    result = tasks.execute_terminal_agent_run.run("run-task-contract-0001", 17)

    assert result["reason_code"] == "worker_lease_lost"
    assert len(repository.finished) == 1


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


def test_reconcile_queued_terminal_agent_dispatch_rejects_invalid_limit(settings):
    """Invalid reconciliation bounds fail before repository access."""

    settings.TERMINAL_QUEUED_INTAKE_ENABLED = True
    settings.TERMINAL_QUEUED_WORKER_ENABLED = True

    result = tasks.reconcile_queued_terminal_agent_dispatch.run(limit=0)

    assert result == {
        "outcome": "failed",
        "success": False,
        "reason_code": "DISPATCH_RECONCILIATION_LIMIT_INVALID",
        "requested": 0,
        "examined": 0,
        "dispatched": 0,
        "failed": 0,
    }


def test_reconcile_queued_terminal_agent_dispatch_blocks_when_worker_disabled(
    settings, monkeypatch
):
    """Reconciliation stays dormant unless both queued flags are enabled."""

    settings.TERMINAL_QUEUED_INTAKE_ENABLED = True
    settings.TERMINAL_QUEUED_WORKER_ENABLED = False
    monkeypatch.setattr(
        tasks,
        "_repo",
        lambda: pytest.fail("blocked reconciliation must not query the repository"),
    )

    result = tasks.reconcile_queued_terminal_agent_dispatch.run()

    assert result["outcome"] == "blocked"
    assert result["reason_code"] == "queued_worker_disabled"


def test_reconcile_queued_terminal_agent_dispatch_republishes_ids(monkeypatch, settings):
    """Reconciliation publishes only the durable run/task identifiers."""

    settings.TERMINAL_QUEUED_INTAKE_ENABLED = True
    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(None)
    repository.dispatch_candidates = (
        TerminalAgentBrokerEnvelope("run-reconcile-contract-0001", 17),
        TerminalAgentBrokerEnvelope("run-reconcile-contract-0002", 18),
    )
    dispatched: list[dict[str, object]] = []
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(
        tasks.execute_terminal_agent_run,
        "apply_async",
        lambda **kwargs: dispatched.append(kwargs),
    )

    result = tasks.reconcile_queued_terminal_agent_dispatch.run(limit=10)

    assert result == {
        "outcome": "success",
        "success": True,
        "reason_code": "dispatch_reconciliation_completed",
        "requested": 10,
        "examined": 2,
        "dispatched": 2,
        "failed": 0,
    }
    assert dispatched == [
        {"args": ["run-reconcile-contract-0001", 17], "queue": "terminal_agent"},
        {"args": ["run-reconcile-contract-0002", 18], "queue": "terminal_agent"},
    ]


def test_reconcile_queued_terminal_agent_dispatch_reports_broker_failure(monkeypatch, settings):
    """A broker outage is reported without mutating the durable queue rows."""

    settings.TERMINAL_QUEUED_INTAKE_ENABLED = True
    settings.TERMINAL_QUEUED_WORKER_ENABLED = True
    repository = _FakeRepository(None)
    repository.dispatch_candidates = (
        TerminalAgentBrokerEnvelope("run-reconcile-contract-0003", 19),
    )
    monkeypatch.setattr(tasks, "_repo", lambda: repository)
    monkeypatch.setattr(
        tasks.execute_terminal_agent_run,
        "apply_async",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    result = tasks.reconcile_queued_terminal_agent_dispatch.run()

    assert result == {
        "outcome": "failed",
        "success": False,
        "reason_code": "dispatch_reconciliation_failed",
        "requested": 100,
        "examined": 1,
        "dispatched": 0,
        "failed": 1,
    }
