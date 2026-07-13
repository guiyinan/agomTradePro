"""pulse runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_pulse_current() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.pulse.get_current()


def _fallback_get_pulse_history(limit: int = 20) -> list[dict[str, Any]]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.pulse.get_history(limit=limit)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_pulse_current": _fallback_get_pulse_current,
    "get_pulse_history": _fallback_get_pulse_history,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {}
