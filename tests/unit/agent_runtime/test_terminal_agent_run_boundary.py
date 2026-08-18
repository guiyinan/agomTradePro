"""Failing-first guards for the future queued API composition boundary."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.agent_runtime.application.terminal_agent_run_boundary import (
    TerminalQueuedRunApplicationBoundary,
)
from apps.agent_runtime.application.terminal_agent_run_ports import (
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


class _FakeAdmissionPort:
    def __init__(self, result: TerminalAgentRunContract) -> None:
        self.result = result
        self.calls: list[TerminalQueuedSubmissionRequest] = []

    def submit(self, request: TerminalQueuedSubmissionRequest) -> TerminalAgentRunContract:
        self.calls.append(request)
        return self.result


def _request(
    runtime_mode: TerminalRuntimeMode = TerminalRuntimeMode.WEB_QUEUED,
) -> TerminalQueuedSubmissionRequest:
    accepted_at = datetime(2026, 8, 18, tzinfo=UTC)
    submission = TerminalRunSubmission(
        selector=TerminalRunSelector(
            run_id="run-20260818-0001",
            task_id=17,
            actor_user_id=41,
            client_request_id="request-0001",
        ),
        runtime_mode=runtime_mode,
        request_digest="a" * 64,
        accepted_at=accepted_at,
        deadline_at=accepted_at + timedelta(minutes=1),
    )
    return TerminalQueuedSubmissionRequest(submission=submission, message="hello")


def test_boundary_delegates_only_to_queued_application_use_case() -> None:
    """The future API boundary delegates once and preserves the queued contract."""

    request = _request()
    result = TerminalAgentRunContract(
        submission=request.submission,
        dispatch_status=TerminalRunStatus.QUEUED,
    )
    port = _FakeAdmissionPort(result)

    assert TerminalQueuedRunApplicationBoundary(port).submit(request) is result
    assert port.calls == [request]


def test_boundary_rejects_legacy_inline_mode_before_adapter_call() -> None:
    """Legacy inline and local CLI submissions cannot enter the queued boundary."""

    request = _request(TerminalRuntimeMode.LEGACY_INLINE)
    port = _FakeAdmissionPort(TerminalAgentRunContract(submission=request.submission))

    with pytest.raises(TerminalRunContractError, match="web_queued"):
        TerminalQueuedRunApplicationBoundary(port).submit(request)

    assert port.calls == []


def test_boundary_source_has_no_legacy_inline_or_infrastructure_dependency() -> None:
    """The composition boundary stays pure until TAR-02 supplies infrastructure."""

    source_path = Path("apps/agent_runtime/application/terminal_agent_run_boundary.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert all("infrastructure" not in name for name in imported_names)
    assert all("celery" not in name.casefold() for name in imported_names)
    assert "OpenAIAgentsTerminalService" not in source
    assert "terminal_agent_service" not in source
    assert ".objects" not in source
