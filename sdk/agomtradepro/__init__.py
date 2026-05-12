"""
AgomTradePro SDK

Python SDK for AgomTradePro - Macro Environment Admission System.
"""

from .client import AgomTradeProClient
from .config import AuthConfig, ClientConfig, get_default_config, load_config
from .exceptions import (
    AgomTradeProAPIError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    raise_for_status,
)
from .exceptions import (
    ConnectionError as SDKConnectionError,
)
from .exceptions import (
    TimeoutError as SDKTimeoutError,
)
from .types import (
    BacktestParams,
    BacktestResult,
    CreateSignalParams,
    EventType,
    GateLevel,
    GrowthLevel,
    InflationLevel,
    InvestmentSignal,
    MacroDataPoint,
    MacroIndicator,
    PolicyEvent,
    PolicyGear,
    PolicyLevel,
    PolicyStatus,
    Portfolio,
    Position,
    RegimeCalculationParams,
    RegimeState,
    RegimeType,
    SentimentGateState,
    SignalEligibilityResult,
    SignalStatus,
    WorkbenchEvent,
    WorkbenchItemsResult,
    WorkbenchSummary,
)

__version__ = "1.0.0"
__all__ = [
    # Version
    "__version__",
    # Client
    "AgomTradeProClient",
    # Config
    "AuthConfig",
    "ClientConfig",
    "load_config",
    "get_default_config",
    # Exceptions
    "AgomTradeProAPIError",
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
    "PolicyLevel",
    "GateLevel",
    "EventType",
    "PolicyStatus",
    "PolicyEvent",
    "WorkbenchSummary",
    "WorkbenchEvent",
    "WorkbenchItemsResult",
    "SentimentGateState",
    # Types - Backtest
    "BacktestParams",
    "BacktestResult",
    # Types - Account
    "Position",
    "Portfolio",
]
