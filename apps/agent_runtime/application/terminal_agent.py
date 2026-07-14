"""Terminal agent DTOs and use cases."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class TerminalAgentChatRequestDTO:
    """Application DTO for one terminal agent chat request."""

    message: str
    session_id: str
    user_id: int | None
    username: str
    user_role: str
    user_is_admin: bool
    mcp_enabled: bool
    provider_ref: Any | None = None
    model: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalAgentEventDTO:
    """Normalized agent event consumable by terminal SSE clients."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalAgentChatResponseDTO:
    """Normalized non-stream terminal chat response."""

    reply: str
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TerminalAgentService(Protocol):
    """Service contract for terminal agent execution."""

    def run_chat(self, request: TerminalAgentChatRequestDTO) -> TerminalAgentChatResponseDTO:
        """Execute one non-stream terminal chat request."""
        ...

    def stream_chat(self, request: TerminalAgentChatRequestDTO) -> Iterator[TerminalAgentEventDTO]:
        """Yield normalized events for one streamed terminal chat request."""
        ...


class TerminalCapabilityGateway(Protocol):
    """Gateway for Terminal-visible MCP capability discovery and matching."""

    def list_terminal_mcp_capabilities(
        self,
        *,
        session_id: str,
        user_id: int | None,
        user_is_admin: bool,
        mcp_enabled: bool,
        provider_name: str | None,
        model: str | None,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return normalized MCP capability records visible to the request."""
        ...


class TerminalApprovalGateway(Protocol):
    """Gateway for durable approval of Terminal-originated MCP calls."""

    def stage_terminal_mcp_capability(
        self,
        *,
        capability_key: str,
        arguments: dict[str, Any],
        risk_level: str,
        summary: str,
        session_id: str,
        user_id: int | None,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist and submit one MCP capability proposal for human approval."""
        ...

    def match_terminal_mcp_capability(
        self,
        *,
        message: str,
        capability_keys: list[str],
    ) -> dict[str, Any] | None:
        """Return the best high-confidence capability match, if any."""
        ...


class RunTerminalAgentChatUseCase:
    """Execute one non-stream terminal agent request."""

    def __init__(self, service: TerminalAgentService) -> None:
        self._service = service

    def execute(self, request: TerminalAgentChatRequestDTO) -> TerminalAgentChatResponseDTO:
        """Run one terminal chat request and return a compact DTO."""

        return self._service.run_chat(request)


class StreamTerminalAgentChatUseCase:
    """Stream normalized events for one terminal agent request."""

    def __init__(self, service: TerminalAgentService) -> None:
        self._service = service

    def execute(self, request: TerminalAgentChatRequestDTO) -> Iterator[TerminalAgentEventDTO]:
        """Return the service stream iterator."""

        return self._service.stream_chat(request)
