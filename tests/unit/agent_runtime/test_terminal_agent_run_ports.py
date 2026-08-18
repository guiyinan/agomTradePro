"""Pure TAR-01 application-boundary tests; no I/O or Agent SDK."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_agent_run_ports import (
    SubmitTerminalQueuedRunUseCase,
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalRunContractError,
    TerminalRunSelector,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)


def _submission(
    *,
    runtime_mode: TerminalRuntimeMode = TerminalRuntimeMode.WEB_QUEUED,
    run_suffix: str = "0001",
) -> TerminalRunSubmission:
    """Build a valid immutable submission for the boundary tests."""

    accepted_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    return TerminalRunSubmission(
        selector=TerminalRunSelector(
            run_id=f"run-20260818-{run_suffix}",
            task_id=17,
            actor_user_id=41,
            client_request_id=f"request-{run_suffix}",
        ),
        runtime_mode=runtime_mode,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )


@dataclass
class _FakeAdmissionPort:
    """Test-only adapter standing in for the future durable admission port."""

    result: TerminalAgentRunContract
    calls: list[TerminalQueuedSubmissionRequest] = field(default_factory=list)

    def submit(
        self,
        request: TerminalQueuedSubmissionRequest,
    ) -> TerminalAgentRunContract:
        """Record the call and return the configured run contract."""

        self.calls.append(request)
        return self.result


def test_queued_use_case_delegates_once_and_preserves_identity() -> None:
    """The application boundary delegates but does not execute Agent work."""

    submission = _submission()
    request = TerminalQueuedSubmissionRequest(submission=submission, message="hello")
    run = TerminalAgentRunContract(submission=submission)
    port = _FakeAdmissionPort(result=run)

    result = SubmitTerminalQueuedRunUseCase(port).execute(request)

    assert result is run
    assert port.calls == [request]


def test_queued_use_case_rejects_non_web_mode_before_port_call() -> None:
    """Local CLI and legacy inline modes cannot cross the web queue port."""

    submission = _submission(runtime_mode=TerminalRuntimeMode.LOCAL_CLI)
    request = TerminalQueuedSubmissionRequest(submission=submission, message="hello")
    port = _FakeAdmissionPort(result=TerminalAgentRunContract(submission=submission))

    with pytest.raises(TerminalRunContractError, match="web_queued"):
        SubmitTerminalQueuedRunUseCase(port).execute(request)

    assert port.calls == []


def test_queued_use_case_rejects_adapter_identity_substitution() -> None:
    """An adapter cannot silently rebind an accepted request to another run."""

    requested = _submission()
    returned = _submission(run_suffix="0002")
    request = TerminalQueuedSubmissionRequest(submission=requested, message="hello")
    port = _FakeAdmissionPort(result=TerminalAgentRunContract(submission=returned))

    with pytest.raises(TerminalRunContractError, match="immutable run identity"):
        SubmitTerminalQueuedRunUseCase(port).execute(request)


def test_ports_module_has_no_infrastructure_or_inline_agent_dependency() -> None:
    """The future intake boundary stays pure until TAR-02 supplies adapters."""

    source_path = Path("apps/agent_runtime/application/terminal_agent_run_ports.py")
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
    assert "OpenAIAgentsTerminalService" not in source
    assert ".objects" not in source


def test_status_argument_is_not_used_to_bypass_application_boundary() -> None:
    """Returned state remains the adapter's contract, not an inline side effect."""

    submission = _submission()
    queued_run = TerminalAgentRunContract(
        submission=submission,
        dispatch_status=TerminalRunStatus.QUEUED,
    )
    request = TerminalQueuedSubmissionRequest(submission=submission, message="hello")

    result = SubmitTerminalQueuedRunUseCase(_FakeAdmissionPort(result=queued_run)).execute(request)

    assert result.dispatch_status is TerminalRunStatus.QUEUED
