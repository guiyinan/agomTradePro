"""App-neutral factory for the Broker-owned R8 monitoring read port."""

from __future__ import annotations

from collections.abc import Callable

_factory: Callable[[str], object] | None = None


def configure_r8_broker_monitoring_factory(factory: Callable[[str], object]) -> None:
    """Register the Broker-owned exact receipt provider factory."""

    global _factory
    _factory = factory


def build_r8_broker_monitoring_provider(*, using: str) -> object:
    """Build the provider or fail closed before Broker registration."""

    if _factory is None:
        raise RuntimeError("r8_broker_monitoring_factory_unconfigured")
    return _factory(using)


__all__ = [
    "build_r8_broker_monitoring_provider",
    "configure_r8_broker_monitoring_factory",
]
