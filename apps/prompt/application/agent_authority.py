"""Fail-closed authority gate for server-side Agent Runtime composition.

The public Agent API is a transport boundary.  User-owned portfolio data may
only be exposed after an authenticated owner/tenant authority provider is
composed.  Until that source exists, this module blocks portfolio scopes and
tools before any model or portfolio provider call.
"""

from __future__ import annotations

from typing import Any, Protocol

AGENT_AUTHORITY_NOT_WIRED = "agent_authority_not_wired"
PORTFOLIO_CONTEXT_SCOPE = "portfolio"
PORTFOLIO_TOOL_NAMES = frozenset(
    {
        "get_portfolio_snapshot",
        "get_portfolio_positions",
        "get_portfolio_cash",
    }
)


class AgentAuthorityGate(Protocol):
    """Application boundary for server-owned Agent authority decisions."""

    def check(
        self,
        *,
        context_scope: list[str] | None,
        context_params: dict[str, Any] | None,
        tool_names: list[str] | None,
    ) -> str | None:
        """Return a stable blocker code, or ``None`` when the request is allowed."""


class UnwiredAgentAuthorityGate:
    """Block user-owned portfolio access until an immutable authority source exists."""

    def check(
        self,
        *,
        context_scope: list[str] | None,
        context_params: dict[str, Any] | None,
        tool_names: list[str] | None,
    ) -> str | None:
        """Fail closed without trusting caller-supplied owner or portfolio fields."""

        del context_params
        if context_scope and PORTFOLIO_CONTEXT_SCOPE in context_scope:
            return AGENT_AUTHORITY_NOT_WIRED
        if tool_names and PORTFOLIO_TOOL_NAMES.intersection(tool_names):
            return AGENT_AUTHORITY_NOT_WIRED
        return None


__all__ = [
    "AGENT_AUTHORITY_NOT_WIRED",
    "AgentAuthorityGate",
    "PORTFOLIO_CONTEXT_SCOPE",
    "PORTFOLIO_TOOL_NAMES",
    "UnwiredAgentAuthorityGate",
]
