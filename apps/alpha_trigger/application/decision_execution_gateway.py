"""Consumer-owned gateway for Decision Rhythm execution references."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_provider: Callable[[str], dict[str, Any] | None] | None = None


def register_decision_execution_ref_provider(
    provider: Callable[[str], dict[str, Any] | None],
) -> None:
    """Register the provider used to resolve decision execution references."""

    global _provider
    _provider = provider


def get_decision_execution_ref(request_id: str) -> dict[str, Any] | None:
    """Return the execution reference for one decision request."""

    if _provider is None:
        raise RuntimeError("Decision execution reference provider is not registered")
    return _provider(request_id)


__all__ = ["get_decision_execution_ref", "register_decision_execution_ref_provider"]
