"""Application ports for the future durable Terminal Agent queue.

TAR-01 defines the boundary only. TAR-02 will provide persistence and
dispatch adapters; this module intentionally performs no I/O and never
composes the legacy inline Agents SDK service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalRunContractError,
    TerminalRunSubmission,
    TerminalRuntimeMode,
)


@dataclass(frozen=True, slots=True)
class TerminalQueuedSubmissionRequest:
    """Application input for a queued submission before durable admission."""

    submission: TerminalRunSubmission
    message: str

    def __post_init__(self) -> None:
        """Reject an empty message before an adapter is invoked."""

        if not isinstance(self.message, str) or not self.message.strip():
            raise TerminalRunContractError("message must be a non-empty string")


class TerminalQueuedSubmissionPort(Protocol):
    """Port that TAR-02 will implement with durable admission and dispatch."""

    def submit(
        self,
        request: TerminalQueuedSubmissionRequest,
    ) -> TerminalAgentRunContract:
        """Persist and admit a request without running Agent work inline."""

        ...


class SubmitTerminalQueuedRunUseCase:
    """Accept a queued web run without composing the legacy inline service.

    This is the TAR-01 application boundary only. The injected port remains
    unimplemented until TAR-02 supplies durable persistence and dispatch; this
    use case deliberately contains no ORM, broker, Celery, or Agent SDK call.
    """

    def __init__(self, admission_port: TerminalQueuedSubmissionPort) -> None:
        """Create the boundary with a durable-admission port."""

        self._admission_port = admission_port

    def execute(
        self,
        request: TerminalQueuedSubmissionRequest,
    ) -> TerminalAgentRunContract:
        """Submit one web-queued request and preserve its immutable identity."""

        if request.submission.runtime_mode is not TerminalRuntimeMode.WEB_QUEUED:
            raise TerminalRunContractError(
                "queued submission boundary accepts only web_queued mode"
            )

        run = self._admission_port.submit(request)
        if not _same_submission_identity(run.submission, request.submission):
            raise TerminalRunContractError("admission port changed immutable run identity")
        return run


def _same_submission_identity(
    actual: TerminalRunSubmission,
    requested: TerminalRunSubmission,
) -> bool:
    """Check fields that an admission adapter must preserve unchanged."""

    return (
        actual.selector == requested.selector
        and actual.runtime_mode is requested.runtime_mode
        and actual.request_digest == requested.request_digest
    )
