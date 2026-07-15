"""App-neutral registry for the Decision Rhythm request repository factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_factory: Callable[[], Any] | None = None


def register_decision_request_repository_factory(factory: Callable[[], Any]) -> None:
    """Register the owning Decision Rhythm repository factory."""

    global _factory
    _factory = factory


def get_decision_request_repository() -> Any:
    """Return the registered Decision Rhythm request repository."""

    if _factory is None:
        raise RuntimeError("Decision request repository factory is not registered")
    return _factory()


__all__ = ["get_decision_request_repository", "register_decision_request_repository_factory"]
