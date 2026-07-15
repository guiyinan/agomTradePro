"""Domain-neutral gateway for optional Signal context integration."""

from __future__ import annotations

from typing import Any, Protocol


class SignalContextGateway(Protocol):
    """Supply active signals without importing the Signal implementation."""

    def list_active_signals(self) -> list[Any]:
        """Return active signals used to build asset screening context."""


class _EmptySignalContextGateway:
    def list_active_signals(self) -> list[Any]:
        return []


_gateway: SignalContextGateway = _EmptySignalContextGateway()


def register_signal_context_gateway(gateway: SignalContextGateway) -> None:
    """Register the Signal-owned adapter during Django application startup."""

    global _gateway
    _gateway = gateway


def get_signal_context_gateway() -> SignalContextGateway:
    """Return the registered adapter or an empty safe fallback."""

    return _gateway


__all__ = [
    "SignalContextGateway",
    "get_signal_context_gateway",
    "register_signal_context_gateway",
]
