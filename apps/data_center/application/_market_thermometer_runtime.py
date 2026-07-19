"""Runtime bridge between market thermometer owners and the legacy facade.

The compatibility facade ``apps.data_center.application.market_thermometer``
registers itself here at import time. Owner modules resolve the historically
monkeypatched names (provider timeout knobs and
``resolve_market_thermometer_as_of_date``) through this module at call time so
existing test patch paths keep working while owners never import the facade
(one-way dependency rule). When the facade has not been imported yet, the
accessors fall back to the canonical constants and helpers.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .market_thermometer_dates import (
    resolve_market_thermometer_as_of_date as _resolve_as_of_date,
)
from .market_thermometer_specs import (
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES as _DEFAULT_TIMEOUT_OVERRIDES,
)
from .market_thermometer_specs import (
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS as _DEFAULT_TIMEOUT_SECONDS,
)

_FACADE: Any = None


def register_market_thermometer_facade(facade: Any) -> None:
    """Register the compatibility facade as the runtime patch surface."""

    global _FACADE
    _FACADE = facade


def resolve_as_of_date(raw_as_of_date: str = "", **kwargs: Any) -> date:
    """Resolve the decision-safe date through the legacy patch surface."""

    if _FACADE is not None:
        return _FACADE.resolve_market_thermometer_as_of_date(raw_as_of_date, **kwargs)
    return _resolve_as_of_date(raw_as_of_date, **kwargs)


def provider_timeout_seconds() -> float:
    """Return the provider timeout honored by legacy monkeypatch paths."""

    if _FACADE is not None:
        return float(_FACADE.MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS)
    return float(_DEFAULT_TIMEOUT_SECONDS)


def provider_timeout_overrides() -> dict[str, float]:
    """Return the per-component timeout overrides honored by legacy patches."""

    if _FACADE is not None:
        return _FACADE.MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES
    return _DEFAULT_TIMEOUT_OVERRIDES
