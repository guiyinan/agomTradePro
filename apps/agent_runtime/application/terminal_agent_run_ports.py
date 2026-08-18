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
