"""
AI Capability Catalog Domain Interfaces.

Protocol definitions for dependency injection.
"""

from typing import Any, List, Optional, Protocol

from .entities import (
    CapabilityDefinition,
    CapabilityRoutingLog,
    CapabilitySyncLog,
    RoutingContext,
    RoutingDecision,
)


class CapabilityRepositoryProtocol(Protocol):
    """Protocol for capability repository."""

    def get_by_key(self, capability_key: str) -> CapabilityDefinition | None:
        """Get a capability by its key."""
        ...

    def get_all_enabled(self) -> list[CapabilityDefinition]:
        """Get all enabled capabilities."""
        ...

    def get_by_source_type(self, source_type: str) -> list[CapabilityDefinition]:
        """Get capabilities by source type."""
        ...

    def get_by_route_group(self, route_group: str) -> list[CapabilityDefinition]:
        """Get capabilities by route group."""
        ...

    def save(self, capability: CapabilityDefinition) -> CapabilityDefinition:
        """Save a capability."""
        ...

    def bulk_upsert(
        self,
        capabilities: list[CapabilityDefinition],
    ) -> dict[str, int]:
        """Bulk upsert capabilities. Returns counts of created/updated."""
        ...

    def disable_missing(
        self,
        source_type: str,
        existing_keys: list[str],
    ) -> int:
        """Disable capabilities that are no longer in source."""
        ...


class RoutingLogRepositoryProtocol(Protocol):
    """Protocol for routing log repository."""

    def save(self, log: CapabilityRoutingLog) -> CapabilityRoutingLog:
        """Save a routing log."""
        ...

    def get_by_session(self, session_id: str) -> list[CapabilityRoutingLog]:
        """Get logs by session ID."""
        ...


class SyncLogRepositoryProtocol(Protocol):
    """Protocol for sync log repository."""

    def save(self, log: CapabilitySyncLog) -> CapabilitySyncLog:
        """Save a sync log."""
        ...

    def get_latest(self, sync_type: str) -> CapabilitySyncLog | None:
        """Get the latest sync log of a given type."""
        ...


class AIProviderProtocol(Protocol):
    """Protocol for AI provider in routing decisions."""

    def classify_intent(
        self,
        message: str,
        candidates: list[dict[str, Any]],
        provider_name: str | None = None,
        model: str | None = None,
    ) -> RoutingDecision:
        """Classify user intent and select capability."""
        ...


class BuiltinExecutorProtocol(Protocol):
    """Protocol for builtin capability executor."""

    def execute(
        self,
        handler: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a builtin capability."""
        ...


class TerminalCommandExecutorProtocol(Protocol):
    """Protocol for terminal command executor."""

    def execute(
        self,
        command_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a terminal command."""
        ...


class McpToolExecutorProtocol(Protocol):
    """Protocol for MCP tool executor."""

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an MCP tool."""
        ...


class ApiExecutorProtocol(Protocol):
    """Protocol for internal API executor."""

    def execute(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an internal API call."""
        ...
