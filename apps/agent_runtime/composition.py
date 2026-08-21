"""Account/runtime composition roots for the queued Terminal Agent path."""

from __future__ import annotations

from apps.agent_runtime.infrastructure.terminal_agent_run_repository import (
    TerminalAgentRunRepository,
)


def get_terminal_agent_run_repository() -> TerminalAgentRunRepository:
    """Build the default same-database durable run repository."""

    return TerminalAgentRunRepository()
