"""Pure composition boundary for the future queued Terminal Agent API.

TAR-01 owns the dependency direction, while TAR-02 will provide the durable
admission adapter.  This module intentionally exposes only the queued use
case and never imports or constructs the legacy inline Agent service.
"""

from __future__ import annotations

from apps.agent_runtime.application.terminal_agent_run_ports import (
    SubmitTerminalQueuedRunUseCase,
    TerminalQueuedSubmissionPort,
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import TerminalAgentRunContract


class TerminalQueuedRunApplicationBoundary:
    """Expose the only application dependency allowed for a queued API route."""

    def __init__(self, admission_port: TerminalQueuedSubmissionPort) -> None:
        """Bind a future durable-admission port without performing I/O."""

        self._submit = SubmitTerminalQueuedRunUseCase(admission_port)

    def submit(self, request: TerminalQueuedSubmissionRequest) -> TerminalAgentRunContract:
        """Validate and delegate one web-queued request to the application use case."""

        return self._submit.execute(request)
