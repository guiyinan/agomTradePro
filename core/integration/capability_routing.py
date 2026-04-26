"""Bridge helpers for AI capability routing."""

from __future__ import annotations

from typing import Any

from apps.ai_capability.application.facade import CapabilityRoutingFacade


def route_terminal_message(**kwargs: Any) -> dict[str, Any]:
    """Route one terminal chat message through the AI capability facade."""

    return CapabilityRoutingFacade().route(**kwargs)
