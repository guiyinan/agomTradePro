"""
Data Center — Domain Layer Enums

Defines capability types for the unified data provider registry,
covering all eight data domains managed by the data center.
"""

from enum import Enum


class DataCapability(Enum):
    """Eight data-domain capabilities for cross-domain provider registration.

    Providers declare which capabilities they support; the registry dispatches
    requests by capability with priority, failover, and circuit-breaker support.
    """

    # Macro economic indicators (GDP, CPI, PMI, SHIBOR, M2, …)
    MACRO = "macro"

    # Historical OHLCV price bars (stocks, ETFs, indices)
    HISTORICAL_PRICE = "historical_price"

    # Real-time / intraday quote snapshots
    REALTIME_QUOTE = "realtime_quote"

    # Fund net asset value (NAV) facts
    FUND_NAV = "fund_nav"

    # Company financial statements (income, balance-sheet, cash-flow)
    FINANCIAL = "financial"

    # Valuation multiples (PE, PB, PS, …)
    VALUATION = "valuation"

    # Sector / index constituent membership
    SECTOR_MEMBERSHIP = "sector_membership"

    # News articles tied to stocks or sectors
    NEWS = "news"

    # Capital-flow data (main-force / retail net inflows)
    CAPITAL_FLOW = "capital_flow"


class ProviderHealthStatus(Enum):
    """Runtime health state of a registered provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


class AssetType(Enum):
    """Canonical asset type for the master data table."""

    STOCK = "stock"
    ETF = "etf"
    INDEX = "index"
    FUND = "fund"
    BOND = "bond"
    FUTURES = "futures"
    CRYPTO = "crypto"
    OTHER = "other"


class MarketExchange(Enum):
    """Primary listing exchange."""

    SSE = "SSE"     # Shanghai
    SZSE = "SZSE"   # Shenzhen
    BSE = "BSE"     # Beijing
    HKEX = "HKEX"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    OTHER = "OTHER"


class DataQualityStatus(Enum):
    """Data quality flag attached to every stored fact."""

    VALID = "valid"
    STALE = "stale"        # data is older than max allowed age
    ESTIMATED = "estimated"  # interpolated or modelled value
    ERROR = "error"        # parse/fetch error
    MISSING = "missing"    # expected but absent


class PriceAdjustment(Enum):
    """Price split/dividend adjustment method."""

    NONE = "none"
    FORWARD = "forward"    # 前复权
    BACKWARD = "backward"  # 后复权


class FinancialPeriodType(Enum):
    """Financial statement reporting period."""

    ANNUAL = "annual"
    SEMI_ANNUAL = "semi_annual"
    QUARTERLY = "quarterly"
    TTM = "ttm"
