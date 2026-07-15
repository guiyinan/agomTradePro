"""Domain-neutral gateway for optional Terminal capability integration."""

from __future__ import annotations

from typing import Any, Protocol


class TerminalCapabilityGateway(Protocol):
    """Expose Terminal operations without importing its implementation."""

    def get_runtime_settings(self) -> dict[str, Any]:
        """Return Terminal-owned runtime settings used by capability routing."""

    def list_active_commands(self) -> list[dict[str, Any]]:
        """Return serializable command descriptors for catalog synchronization."""

    def execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one Terminal command and return a neutral result payload."""


class _UnavailableTerminalCapabilityGateway:
    """Safe fallback used when Terminal is not installed or not initialized."""

    def get_runtime_settings(self) -> dict[str, Any]:
        return {}

    def list_active_commands(self) -> list[dict[str, Any]]:
        return []

    def execute_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        return {
            "success": False,
            "error": "Terminal capability gateway is unavailable.",
            "metadata": {},
            "confirmation_required": False,
        }


_gateway: TerminalCapabilityGateway = _UnavailableTerminalCapabilityGateway()


def register_terminal_capability_gateway(gateway: TerminalCapabilityGateway) -> None:
    """Register the Terminal-owned adapter during Django application startup."""

    global _gateway
    _gateway = gateway


def get_terminal_capability_gateway() -> TerminalCapabilityGateway:
    """Return the registered Terminal adapter or a safe unavailable fallback."""

    return _gateway


__all__ = [
    "TerminalCapabilityGateway",
    "get_terminal_capability_gateway",
    "register_terminal_capability_gateway",
]
