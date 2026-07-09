"""Terminal agent DTOs and use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


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

