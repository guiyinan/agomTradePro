"""
AgomTradePro SDK - Agent Context Module

WP-M2-03: Provides context snapshot retrieval for AI agent tasks.

Public methods:
- get_context_snapshot (for any domain)
- get_research_context
- get_monitoring_context
- get_decision_context
- get_execution_context
- get_ops_context
"""

from typing import Any

from .base import BaseModule


class AgentContextModule(BaseModule):
    """
    Agent Context module.

    Retrieves domain-specific context snapshots used by AI agents
    to understand the current system state before acting.
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/agent-runtime/context")

    def get_context_snapshot(self, domain: str) -> dict[str, Any]:
        """
        Get context snapshot for a given domain.

        Args:
            domain: Task domain (research/monitoring/decision/execution/ops)

        Returns:
            Dict with request_id, domain, generated_at, and all summary sections

        Raises:
            ValidationError: If domain is invalid
            NotFoundError: If context endpoint not found

        Example:
            >>> client = AgomTradeProClient()
            >>> ctx = client.agent_context.get_context_snapshot("research")
            >>> print(ctx["regime_summary"]["dominant_regime"])
        """
        return self._get(f"{domain}/")

    def get_research_context(self) -> dict[str, Any]:
        """Get research domain context snapshot."""
        return self.get_context_snapshot("research")

    def get_monitoring_context(self) -> dict[str, Any]:
        """Get monitoring domain context snapshot."""
        return self.get_context_snapshot("monitoring")

    def get_decision_context(self) -> dict[str, Any]:
        """Get decision domain context snapshot."""
        return self.get_context_snapshot("decision")

    def get_execution_context(self) -> dict[str, Any]:
        """Get execution domain context snapshot."""
        return self.get_context_snapshot("execution")

    def get_ops_context(self) -> dict[str, Any]:
        """Get ops domain context snapshot."""
        return self.get_context_snapshot("ops")
