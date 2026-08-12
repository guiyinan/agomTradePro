"""App-neutral factories for Data Center and Regime R3 owner reads."""

from __future__ import annotations

from collections.abc import Callable

_pit_factory: Callable[[str], object] | None = None
_regime_factory: Callable[[str], object] | None = None


def configure_r3_pit_projection_factory(factory: Callable[[str], object]) -> None:
    """Register the Data Center-owned PIT projection factory."""

    global _pit_factory
    _pit_factory = factory


def configure_r3_regime_assignment_factory(factory: Callable[[str], object]) -> None:
    """Register the Regime-owned assignment receipt factory."""

    global _regime_factory
    _regime_factory = factory


def build_r3_pit_projection_provider(*, using: str) -> object:
    """Build the PIT provider or fail closed before owner registration."""

    if _pit_factory is None:
        raise RuntimeError("r3_pit_projection_factory_unconfigured")
    return _pit_factory(using)


def build_r3_regime_assignment_reader(*, using: str) -> object:
    """Build the assignment reader or fail closed before owner registration."""

    if _regime_factory is None:
        raise RuntimeError("r3_regime_assignment_factory_unconfigured")
    return _regime_factory(using)


__all__ = [
    "build_r3_pit_projection_provider",
    "build_r3_regime_assignment_reader",
    "configure_r3_pit_projection_factory",
    "configure_r3_regime_assignment_factory",
]
