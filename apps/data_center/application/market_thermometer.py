"""Compatibility exports for market thermometer application use cases.

Implementations live in focused owner modules (specs, config/override
management, investor-account import, input sync, and snapshot calculation).
Keep this module as the stable import surface and the monkeypatch surface for
callers and tests: it registers itself with ``_market_thermometer_runtime``
so owner modules resolve patched names through this module at call time
without importing it back.
"""

import sys as _sys

from ._market_thermometer_runtime import (
    register_market_thermometer_facade as _register_market_thermometer_facade,
)
from .market_thermometer_calculate import CalculateMarketThermometerUseCase
from .market_thermometer_config_use_cases import (
    ManageMarketThermometerConfigUseCase,
    ManageMarketThermometerUserOverrideUseCase,
    build_market_thermometer_override_payload,
)
from .market_thermometer_dates import resolve_market_thermometer_as_of_date
from .market_thermometer_import_use_cases import ImportInvestorAccountsUseCase
from .market_thermometer_specs import (
    DEFAULT_MARKET_DATA_SOURCE_TYPES,
    DEFAULT_NEWS_SOURCE_TYPES,
    ETF_MAIN_FLOW_CODE,
    ETF_NET_FLOW_PROVIDER_TIMEOUT_SECONDS,
    ETF_SIZE_FLOW_CODE,
    MARKET_COMPONENT_SPECS,
    MARKET_NEWS_POSITIVE_RATIO_CODE,
    MARKET_THERMOMETER_CONSENSUS_SOURCE,
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES,
    MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS,
    MARKET_THERMOMETER_SOURCE_TOLERANCE,
    RECOVERABLE_THERMOMETER_EXCEPTION_NAMES,
    RECOVERABLE_THERMOMETER_EXCEPTIONS,
)
from .market_thermometer_sync import SyncMarketThermometerInputsUseCase

_register_market_thermometer_facade(_sys.modules[__name__])

__all__ = [
    "CalculateMarketThermometerUseCase",
    "DEFAULT_MARKET_DATA_SOURCE_TYPES",
    "DEFAULT_NEWS_SOURCE_TYPES",
    "ETF_MAIN_FLOW_CODE",
    "ETF_NET_FLOW_PROVIDER_TIMEOUT_SECONDS",
    "ETF_SIZE_FLOW_CODE",
    "ImportInvestorAccountsUseCase",
    "MARKET_COMPONENT_SPECS",
    "MARKET_NEWS_POSITIVE_RATIO_CODE",
    "MARKET_THERMOMETER_CONSENSUS_SOURCE",
    "MARKET_THERMOMETER_PROVIDER_TIMEOUT_OVERRIDES",
    "MARKET_THERMOMETER_PROVIDER_TIMEOUT_SECONDS",
    "MARKET_THERMOMETER_SOURCE_TOLERANCE",
    "ManageMarketThermometerConfigUseCase",
    "ManageMarketThermometerUserOverrideUseCase",
    "RECOVERABLE_THERMOMETER_EXCEPTIONS",
    "RECOVERABLE_THERMOMETER_EXCEPTION_NAMES",
    "SyncMarketThermometerInputsUseCase",
    "build_market_thermometer_override_payload",
    "resolve_market_thermometer_as_of_date",
]
