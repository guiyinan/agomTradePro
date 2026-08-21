"""Dormant TAR-01 chaos/recovery contract tests.

The tests cover the finite state machine only.  No worker, Redis, broker, or
production fault is injected here; those remain a separate authorization gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    InvalidTerminalRunTransition,
    TerminalAgentRunContract,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
    transition_terminal_run,
)


def _run() -> TerminalAgentRunContract:
    """Build a valid owner-scoped run for state-machine checks."""

    accepted_at = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    return TerminalAgentRunContract(
        submission=TerminalRunSubmission(
            selector=TerminalRunSelector(
                run_id="run-chaos-contract",
                task_id=41,
                actor_user_id=7,
                client_request_id="request-chaos-contract",
            ),
            runtime_mode=TerminalRuntimeMode.WEB_QUEUED,
            request_digest="a" * 64,
            accepted_at=accepted_at,
            deadline_at=accepted_at + timedelta(minutes=5),
        ),
        dispatch_status=TerminalRunStatus.CLAIMED,
    )


def test_worker_loss_can_requeue_or_fail_but_not_skip_recovery_edges() -> None:
    """An orphaned run has only the two explicit recovery transitions."""

    assert transition_terminal_run(TerminalRunStatus.CLAIMED, TerminalRunStatus.ORPHANED) is (
        TerminalRunStatus.ORPHANED
    )
    assert transition_terminal_run(TerminalRunStatus.ORPHANED, TerminalRunStatus.QUEUED) is (
        TerminalRunStatus.QUEUED
    )
    assert transition_terminal_run(TerminalRunStatus.ORPHANED, TerminalRunStatus.FAILED) is (
        TerminalRunStatus.FAILED
    )
    with pytest.raises(InvalidTerminalRunTransition):
        transition_terminal_run(TerminalRunStatus.ORPHANED, TerminalRunStatus.COMPLETED)


def test_worker_restart_cannot_overwrite_a_terminal_run() -> None:
    """Late delivery is idempotent only for the already applied terminal state."""

    run = _run().transition(TerminalRunStatus.RUNNING).transition(TerminalRunStatus.COMPLETED)
    assert run.dispatch_status is TerminalRunStatus.COMPLETED
    assert run.transition(TerminalRunStatus.COMPLETED).dispatch_status is (
        TerminalRunStatus.COMPLETED
    )
    with pytest.raises(InvalidTerminalRunTransition):
        run.transition(TerminalRunStatus.RUNNING)


def test_chaos_contract_keeps_broker_payload_id_only() -> None:
    """Recovery paths never add prompt, credential, or provider data to a message."""

    assert _run().broker_payload() == {"run_id": "run-chaos-contract", "task_id": 41}
