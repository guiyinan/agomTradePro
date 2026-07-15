"""App-neutral data providers used by Policy hedging orchestration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_position_repository_factory: Callable[[], Any] | None = None
_price_repository_factory: Callable[[], Any] | None = None


def register_position_repository_factory(factory: Callable[[], Any]) -> None:
    """Register the Account position repository factory."""

    global _position_repository_factory
    _position_repository_factory = factory


def register_price_repository_factory(factory: Callable[[], Any]) -> None:
    """Register the Realtime price repository factory."""

    global _price_repository_factory
    _price_repository_factory = factory


def get_position_repository() -> Any:
    """Return the registered Account position repository."""

    if _position_repository_factory is None:
        raise RuntimeError("Policy hedge position provider is not registered")
    return _position_repository_factory()


def get_price_repository() -> Any:
    """Return the registered Realtime price repository."""

    if _price_repository_factory is None:
        raise RuntimeError("Policy hedge price provider is not registered")
    return _price_repository_factory()


__all__ = [
    "get_position_repository",
    "get_price_repository",
    "register_position_repository_factory",
    "register_price_repository_factory",
]
