"""App-neutral factory for the Research-owned R1 trial read port."""

from __future__ import annotations

from collections.abc import Callable

_factory: Callable[[str], object] | None = None


def configure_r1_forecast_trial_evidence_factory(
    factory: Callable[[str], object],
) -> None:
    """Register the Research-owned exact-read provider factory."""

    global _factory
    _factory = factory


def build_r1_forecast_trial_evidence_provider(*, using: str) -> object:
    """Build the provider or fail closed when Research is not configured."""

    if _factory is None:
        raise RuntimeError("r1_forecast_trial_evidence_factory_unconfigured")
    return _factory(using)


__all__ = [
    "build_r1_forecast_trial_evidence_provider",
    "configure_r1_forecast_trial_evidence_factory",
]
