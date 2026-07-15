"""Consumer-owned gateway for Signal reevaluation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_reevaluator: Callable[..., Any] | None = None


def register_signal_reevaluator(reevaluator: Callable[..., Any]) -> None:
    """Register the owning Signal reevaluation provider."""

    global _reevaluator
    _reevaluator = reevaluator


def reevaluate_signals(**kwargs: Any) -> Any:
    """Reevaluate active signals through the registered provider."""

    if _reevaluator is None:
        raise RuntimeError("Signal reevaluation provider is not registered")
    return _reevaluator(**kwargs)


__all__ = ["reevaluate_signals", "register_signal_reevaluator"]
