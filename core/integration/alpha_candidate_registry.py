"""App-neutral registry for the Alpha Trigger candidate repository factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_factory: Callable[[], Any] | None = None


def register_alpha_candidate_repository_factory(factory: Callable[[], Any]) -> None:
    global _factory
    _factory = factory


def get_alpha_candidate_repository() -> Any:
    if _factory is None:
        raise RuntimeError("Alpha candidate repository factory is not registered")
    return _factory()


__all__ = ["get_alpha_candidate_repository", "register_alpha_candidate_repository_factory"]
