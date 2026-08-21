"""Application ports for the future durable Terminal Agent queue.

TAR-01 defines the boundary only. TAR-02 will provide persistence and
dispatch adapters; this module intentionally performs no I/O and never
composes the legacy inline Agents SDK service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalRunContractError,
    TerminalRunStatus,
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


@dataclass(frozen=True, slots=True)
class TerminalRunQueueSummary:
    """Advisory owner and global queue counters for bounded admission.

    The summary is a read snapshot, not an admission reservation.  A future
    TAR-02 composition root must evaluate these counters together with a
    database-serialized admission transaction.
    """

    actor_user_id: int
    user_active: int
    user_queued: int
    global_active: int
    global_queued: int
    worker_ready: bool = False

    def __post_init__(self) -> None:
        """Reject impossible counters before they cross an application port."""

        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise TerminalRunContractError("actor_user_id must be a positive integer")
        for field_name in ("user_active", "user_queued", "global_active", "global_queued"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise TerminalRunContractError(f"{field_name} must be a non-negative integer")
        if self.user_active > self.global_active:
            raise TerminalRunContractError("user_active cannot exceed global_active")
        if self.user_queued > self.global_queued:
            raise TerminalRunContractError("user_queued cannot exceed global_queued")
        if type(self.worker_ready) is not bool:
            raise TerminalRunContractError("worker_ready must be a boolean")


class TerminalQueuedRunStatePort(Protocol):
    """Port for durable owner-scoped lifecycle and queue observations."""

    def get_for_owner(
        self,
        *,
        run_id: str,
        actor_user_id: int,
    ) -> TerminalAgentRunContract | None:
        """Return one run only when the actor owns it."""

        ...

    def transition(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        target: TerminalRunStatus,
        worker_id: str | None = None,
        changed_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Apply one validated lifecycle transition under a row lock."""

        ...

    def cancel(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        requested_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Request cancellation with owner-scoped idempotency."""

        ...

    def queue_summary(self, *, actor_user_id: int) -> TerminalRunQueueSummary:
        """Return advisory owner/global queue counters."""

        ...


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
