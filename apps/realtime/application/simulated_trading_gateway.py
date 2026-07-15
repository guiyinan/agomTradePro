"""Consumer-owned gateway for simulated position access."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_position_repository_factory: Callable[[], Any] | None = None
_held_asset_codes_provider: Callable[[], list[str]] | None = None


def register_simulated_position_providers(
    *,
    repository_factory: Callable[[], Any],
    held_asset_codes_provider: Callable[[], list[str]],
) -> None:
    """Register Simulated Trading position providers."""

    global _position_repository_factory
    global _held_asset_codes_provider
    _position_repository_factory = repository_factory
    _held_asset_codes_provider = held_asset_codes_provider


def get_simulated_position_repository() -> Any:
    """Return the registered simulated-position repository."""

    if _position_repository_factory is None:
        raise RuntimeError("Simulated position repository factory is not registered")
    return _position_repository_factory()


def list_held_asset_codes() -> list[str]:
    """Return held asset codes through the registered provider."""

    if _held_asset_codes_provider is None:
        return []
    return _held_asset_codes_provider()


__all__ = [
    "get_simulated_position_repository",
    "list_held_asset_codes",
    "register_simulated_position_providers",
]
