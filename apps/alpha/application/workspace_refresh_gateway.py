"""Consumer-owned gateway for refreshing Decision Rhythm workspace outputs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_provider: Callable[[], Any] | None = None


def register_default_workspace_refresh_provider(provider: Callable[[], Any]) -> None:
    """Register the provider that refreshes the default decision workspace."""

    global _provider
    _provider = provider


def refresh_default_workspace_recommendations() -> Any:
    """Refresh default workspace recommendations through the registered provider."""

    if _provider is None:
        raise RuntimeError("Default workspace refresh provider is not registered")
    return _provider()


__all__ = [
    "refresh_default_workspace_recommendations",
    "register_default_workspace_refresh_provider",
]
