"""Register Regime resolution for Pulse consumers."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.pulse.application.regime_gateway import register_current_regime_resolver

from . import current_regime


def _resolve_current_regime(*, as_of_date: date) -> Any:
    return current_regime.resolve_current_regime(as_of_date=as_of_date)


def register_regime_pulse_gateway() -> None:
    """Register the current Regime provider for Pulse."""

    register_current_regime_resolver(_resolve_current_regime)


__all__ = ["register_regime_pulse_gateway"]
