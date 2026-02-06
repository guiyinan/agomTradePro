"""
AgomSAAF SDK

Python SDK for AgomSAAF - Macro Environment Admission System.
"""

from .client import AgomSAAFClient
from .config import AuthConfig, ClientConfig, get_default_config, load_config
from .exceptions import (
    AgomSAAFAPIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    ConnectionError as SDKConnectionError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TimeoutError as SDKTimeoutError,
    ValidationError,
    raise_for_status,
)
from .types import (
    BacktestParams,
    BacktestResult,
    CreateSignalParams,
    GrowthLevel,
    InflationLevel,
    InvestmentSignal,
    MacroDataPoint,
    MacroIndicator,
    PolicyEvent,
    PolicyGear,
    PolicyStatus,
    Portfolio,
    Position,
    RegimeCalculationParams,
    RegimeState,
    RegimeType,
    SignalEligibilityResult,
    SignalStatus,
)

__version__ = "1.0.0"
__all__ = [
    # Version
    "__version__",
    # Client
    "AgomSAAFClient",
    # Config
    "AuthConfig",
    "ClientConfig",
    "load_config",
    "get_default_config",
    # Exceptions
    "AgomSAAFAPIError",
    "AuthenticationError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "ServerError",
    "SDKConnectionError",
    "SDKTimeoutError",
    "ConfigurationError",
    "raise_for_status",
    # Types - Regime
    "RegimeType",
    "GrowthLevel",
    "InflationLevel",
    "RegimeState",
    "RegimeCalculationParams",
    # Types - Signal
    "SignalStatus",
    "InvestmentSignal",
    "SignalEligibilityResult",
    "CreateSignalParams",
    # Types - Macro
    "MacroIndicator",
    "MacroDataPoint",
    # Types - Policy
    "PolicyGear",
    "PolicyStatus",
    "PolicyEvent",
    # Types - Backtest
    "BacktestParams",
    "BacktestResult",
    # Types - Account
    "Position",
    "Portfolio",
]
