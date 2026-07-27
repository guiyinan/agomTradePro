"""Consumer-owned gateway for current Regime resolution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Protocol


class PulseRegimeContext(Protocol):
    """Regime fields consumed by Pulse calculation."""

    dominant_regime: str


_resolver: Callable[..., PulseRegimeContext] | None = None


def register_current_regime_resolver(
    resolver: Callable[..., PulseRegimeContext],
) -> None:
    """Register the owning Regime resolver."""

    global _resolver
    _resolver = resolver


def resolve_current_regime(*, as_of_date: date) -> PulseRegimeContext:
    """Resolve current Regime through the registered provider."""

    if _resolver is None:
        raise RuntimeError("Current Regime resolver is not registered")
    return _resolver(as_of_date=as_of_date)


__all__ = [
    "PulseRegimeContext",
    "register_current_regime_resolver",
    "resolve_current_regime",
]
