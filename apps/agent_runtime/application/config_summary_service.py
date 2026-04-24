"""Agent-runtime summaries used by the system config center."""

from __future__ import annotations

from typing import Any, Protocol


class AgentRuntimeConfigSummaryRepository(Protocol):
    """Read model contract for agent-runtime config summaries."""

    def get_operator_summary(self) -> dict[str, Any]:
        """Return operator queue and attention summary."""


class AgentRuntimeConfigSummaryService:
    """Application service for config-center agent-runtime summaries."""

    def __init__(self, repository: AgentRuntimeConfigSummaryRepository):
        self.repository = repository

    def get_operator_summary(self, user: Any) -> dict[str, Any]:
        """Return operator queue and attention summary."""

        return self.repository.get_operator_summary()


_config_summary_repository: AgentRuntimeConfigSummaryRepository | None = None


def configure_agent_runtime_config_summary_repository(
    repository: AgentRuntimeConfigSummaryRepository,
) -> None:
    """Register the agent-runtime config-summary repository."""

    global _config_summary_repository
    _config_summary_repository = repository


def get_agent_runtime_config_summary_service() -> AgentRuntimeConfigSummaryService:
    """Return the configured agent-runtime config-summary service."""

    if _config_summary_repository is None:
        raise RuntimeError("Agent-runtime config summary repository is not configured")
    return AgentRuntimeConfigSummaryService(_config_summary_repository)
