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

import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol, cast

from .market_thermometer_dates import resolve_market_thermometer_as_of_date as _resolve_as_of_date
from .market_thermometer_specs import (
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES as _DEFAULT_TIMEOUT_OVERRIDES,
)
from .market_thermometer_specs import (
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS as _DEFAULT_TIMEOUT_SECONDS,
)

_MAX_PROVIDER_TIMEOUT_SECONDS = 300.0
_MAX_PROVIDER_TIMEOUT_OVERRIDES = 50


class _MarketThermometerFacadeProtocol(Protocol):
    """Minimal compatibility surface published by the legacy facade module."""

    MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS: object
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES: object

    def resolve_market_thermometer_as_of_date(
        self,
        raw_as_of_date: str = "",
        **kwargs: Any,
    ) -> object:
        """Resolve one raw market-thermometer date."""
        ...


_FACADE: _MarketThermometerFacadeProtocol | None = None


def register_market_thermometer_facade(facade: object) -> None:
    """Register the compatibility facade as the runtime patch surface."""

    global _FACADE
    _FACADE = cast(_MarketThermometerFacadeProtocol, facade)


def resolve_as_of_date(raw_as_of_date: str = "", **kwargs: Any) -> date:
    """Resolve the decision-safe date through the legacy patch surface."""

    if _FACADE is not None:
        resolved = _FACADE.resolve_market_thermometer_as_of_date(raw_as_of_date, **kwargs)
        if isinstance(resolved, datetime) or not isinstance(resolved, date):
            raise TypeError("market_thermometer_as_of_date_invalid")
        return resolved
    return _resolve_as_of_date(raw_as_of_date, **kwargs)


def provider_timeout_seconds() -> float:
    """Return the provider timeout honored by legacy monkeypatch paths."""

    if _FACADE is not None:
        raw_timeout = _FACADE.MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS
    else:
        raw_timeout = _DEFAULT_TIMEOUT_SECONDS
    if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float)):
        raise TypeError("market_thermometer_provider_timeout_invalid")
    timeout = float(raw_timeout)
    if not math.isfinite(timeout) or not 0 < timeout <= _MAX_PROVIDER_TIMEOUT_SECONDS:
        raise ValueError("market_thermometer_provider_timeout_invalid")
    return timeout


def provider_timeout_overrides() -> dict[str, float]:
    """Return the per-component timeout overrides honored by legacy patches."""

    if _FACADE is not None:
        raw_overrides = _FACADE.MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES
    else:
        raw_overrides = _DEFAULT_TIMEOUT_OVERRIDES
    if not isinstance(raw_overrides, Mapping):
        raise TypeError("market_thermometer_provider_timeout_overrides_invalid")
    if len(raw_overrides) > _MAX_PROVIDER_TIMEOUT_OVERRIDES:
        raise ValueError("market_thermometer_provider_timeout_overrides_invalid")

    overrides: dict[str, float] = {}
    for component, raw_timeout in raw_overrides.items():
        if not isinstance(component, str) or not component or len(component) > 100:
            raise ValueError("market_thermometer_provider_timeout_overrides_invalid")
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float)):
            raise TypeError("market_thermometer_provider_timeout_overrides_invalid")
        timeout = float(raw_timeout)
        if not math.isfinite(timeout) or not 0 < timeout <= _MAX_PROVIDER_TIMEOUT_SECONDS:
            raise ValueError("market_thermometer_provider_timeout_overrides_invalid")
        overrides[component] = timeout
    return overrides
