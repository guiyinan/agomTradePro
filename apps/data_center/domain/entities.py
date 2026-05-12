"""
Data Center — Domain Layer Entities

Pure Python value objects and domain entities.
No Django, pandas, or external library imports allowed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from apps.data_center.domain.enums import (
    AssetType,
    DataCapability,
    DataQualityStatus,
    FinancialPeriodType,
    MarketExchange,
    PriceAdjustment,
    ProviderHealthStatus,
)

# ---------------------------------------------------------------------------
# Provider configuration value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderConfig:
    """Immutable snapshot of a configured external data provider.

    Mirrors the persistent ProviderConfigModel but lives in the domain as a
    pure value object — no ORM dependency.
    """

    id: int | None
    name: str
    source_type: str          # tushare | akshare | eastmoney | qmt | fred
    is_active: bool
    priority: int             # lower = higher precedence
    api_key: str
    api_secret: str
    http_url: str             # tushare proxy override
    api_endpoint: str
    extra_config: dict[str, Any]
    description: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ProviderConfig.name cannot be empty")
        if not self.source_type:
            raise ValueError("ProviderConfig.source_type cannot be empty")


@dataclass(frozen=True)
class ProviderCapabilityDeclaration:
    """Declares which DataCapability a provider supports at what priority."""

    provider_name: str
    capability: DataCapability
    priority: int


@dataclass(frozen=True)
class ProviderHealthSnapshot:
    """Point-in-time health snapshot for one provider × capability pair."""

    provider_name: str
    capability: DataCapability
    status: ProviderHealthStatus
    consecutive_failures: int = 0
    last_success_at: datetime | None = None
    avg_latency_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "capability": self.capability.value,
            "status": self.status.value,
            "is_healthy": self.status == ProviderHealthStatus.HEALTHY,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "avg_latency_ms": self.avg_latency_ms,
        }


# ---------------------------------------------------------------------------
# Global provider settings value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataProviderSettings:
    """Global provider behaviour settings (singleton in DB)."""

    default_source: str       # tushare | akshare | failover
    enable_failover: bool
    failover_tolerance: float  # e.g. 0.01 = 1 %

    def __post_init__(self) -> None:
        if not 0.0 <= self.failover_tolerance <= 1.0:
            raise ValueError(
                f"failover_tolerance must be in [0, 1], got {self.failover_tolerance}"
            )


# ---------------------------------------------------------------------------
# Connection test result value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConnectionTestResult:
    """Result returned by a provider connectivity probe."""

    success: bool
    status: str   # "success" | "warning" | "error"
    summary: str
    logs: list[str] = field(default_factory=list)
    tested_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "summary": self.summary,
            "logs": self.logs,
            "tested_at": self.tested_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Master data value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssetMaster:
    """Unified master record for any tradable asset."""

    code: str                # canonical code, e.g. "000001.SZ"
    name: str
    short_name: str
    asset_type: AssetType
    exchange: MarketExchange
    is_active: bool = True
    list_date: date | None = None
    delist_date: date | None = None
    sector: str = ""
    industry: str = ""
    currency: str = "CNY"
    total_shares: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("AssetMaster.code cannot be empty")
        if not self.name:
            raise ValueError("AssetMaster.name cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "short_name": self.short_name,
            "asset_type": self.asset_type.value,
            "exchange": self.exchange.value,
            "is_active": self.is_active,
            "list_date": self.list_date.isoformat() if self.list_date else None,
            "delist_date": self.delist_date.isoformat() if self.delist_date else None,
            "sector": self.sector,
            "industry": self.industry,
            "currency": self.currency,
            "total_shares": self.total_shares,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class AssetAlias:
    """One row per (asset_code, source_type) code mapping."""

    asset_code: str
    provider_name: str
    alias_code: str

    def __post_init__(self) -> None:
        if not self.asset_code or not self.provider_name or not self.alias_code:
            raise ValueError("AssetAlias fields cannot be empty")


@dataclass(frozen=True)
class PublisherCatalog:
    """Canonical publisher / institution metadata for provenance governance."""

    code: str
    canonical_name: str
    publisher_class: str
    aliases: list[str] = field(default_factory=list)
    canonical_name_en: str = ""
    country_code: str = "CN"
    website: str = ""
    is_active: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.code or not self.canonical_name or not self.publisher_class:
            raise ValueError("PublisherCatalog core fields cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "canonical_name": self.canonical_name,
            "publisher_class": self.publisher_class,
            "aliases": list(self.aliases),
            "canonical_name_en": self.canonical_name_en,
            "country_code": self.country_code,
            "website": self.website,
            "is_active": self.is_active,
            "description": self.description,
        }


@dataclass(frozen=True)
class IndicatorCatalog:
    """Canonical macro indicator definition."""

    code: str
    name_cn: str
    name_en: str = ""
    description: str = ""
    default_unit: str = ""
    default_period_type: str = "M"
    category: str = ""
    is_active: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.name_cn:
            raise ValueError("IndicatorCatalog fields cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "description": self.description,
            "default_unit": self.default_unit,
            "default_period_type": self.default_period_type,
            "category": self.category,
            "is_active": self.is_active,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class IndicatorUnitRule:
    """Canonical unit-governance rule for one macro indicator."""

    id: int | None
    indicator_code: str
    source_type: str = ""
    dimension_key: str = "other"
    original_unit: str = ""
    storage_unit: str = ""
    display_unit: str = ""
    multiplier_to_storage: float = 1.0
    is_active: bool = True
    priority: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.indicator_code:
            raise ValueError("IndicatorUnitRule.indicator_code cannot be empty")
        if not self.dimension_key:
            raise ValueError("IndicatorUnitRule.dimension_key cannot be empty")
        if self.multiplier_to_storage <= 0:
            raise ValueError("IndicatorUnitRule.multiplier_to_storage must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "indicator_code": self.indicator_code,
            "source_type": self.source_type,
            "dimension_key": self.dimension_key,
            "original_unit": self.original_unit,
            "storage_unit": self.storage_unit,
            "display_unit": self.display_unit,
            "multiplier_to_storage": self.multiplier_to_storage,
            "is_active": self.is_active,
            "priority": self.priority,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Fact table value objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MacroFact:
    """One observation of a macro indicator."""

    indicator_code: str
    reporting_period: date
    value: float
    unit: str
    source: str
    revision_number: int = 0
    published_at: date | None = None
    quality: DataQualityStatus = DataQualityStatus.VALID
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.indicator_code:
            raise ValueError("MacroFact.indicator_code cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_code": self.indicator_code,
            "reporting_period": self.reporting_period.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "revision_number": self.revision_number,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "quality": self.quality.value,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }


@dataclass(frozen=True)
class PriceBar:
    """One OHLCV bar for a tradable asset."""

    asset_code: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    freq: str = "1d"
    adjustment: PriceAdjustment = PriceAdjustment.NONE
    volume: float | None = None
    amount: float | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("PriceBar.asset_code cannot be empty")
        if self.close < 0:
            raise ValueError(f"PriceBar.close cannot be negative: {self.close}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "bar_date": self.bar_date.isoformat(),
            "freq": self.freq,
            "adjustment": self.adjustment.value,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class QuoteSnapshot:
    """Real-time / intraday quote for a tradable asset."""

    asset_code: str
    snapshot_at: datetime
    current_price: float
    source: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    bid: float | None = None
    ask: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("QuoteSnapshot.asset_code cannot be empty")
        if self.current_price < 0:
            raise ValueError(
                f"QuoteSnapshot.current_price cannot be negative: {self.current_price}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "snapshot_at": self.snapshot_at.isoformat(),
            "current_price": self.current_price,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.prev_close,
            "volume": self.volume,
            "amount": self.amount,
            "bid": self.bid,
            "ask": self.ask,
            "source": self.source,
            "extra": self.extra,
        }


@dataclass(frozen=True)
class FundNavFact:
    """One daily NAV observation for a fund."""

    fund_code: str
    nav_date: date
    nav: float
    acc_nav: float | None = None
    daily_return: float | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fund_code:
            raise ValueError("FundNavFact.fund_code cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "nav_date": self.nav_date.isoformat(),
            "nav": self.nav,
            "acc_nav": self.acc_nav,
            "daily_return": self.daily_return,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }


@dataclass(frozen=True)
class FinancialFact:
    """One financial statement metric for an asset in a period."""

    asset_code: str
    period_end: date
    period_type: FinancialPeriodType
    metric_code: str
    value: float
    unit: str = ""
    source: str = ""
    report_date: date | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_code or not self.metric_code:
            raise ValueError("FinancialFact fields cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "period_end": self.period_end.isoformat(),
            "period_type": self.period_type.value,
            "metric_code": self.metric_code,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }


@dataclass(frozen=True)
class ValuationFact:
    """Daily valuation multiples for an asset."""

    asset_code: str
    val_date: date
    pe_ttm: float | None = None
    pe_static: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None
    market_cap: float | None = None
    float_market_cap: float | None = None
    dv_ratio: float | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("ValuationFact.asset_code cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "val_date": self.val_date.isoformat(),
            "pe_ttm": self.pe_ttm,
            "pe_static": self.pe_static,
            "pb": self.pb,
            "ps_ttm": self.ps_ttm,
            "market_cap": self.market_cap,
            "float_market_cap": self.float_market_cap,
            "dv_ratio": self.dv_ratio,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }


@dataclass(frozen=True)
class SectorMembershipFact:
    """Constituent membership of an asset in a sector on an effective date."""

    asset_code: str
    sector_code: str
    effective_date: date
    sector_name: str = ""
    expiry_date: date | None = None
    weight: float | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.sector_code or not self.asset_code:
            raise ValueError("SectorMembershipFact fields cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector_code": self.sector_code,
            "asset_code": self.asset_code,
            "sector_name": self.sector_name,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "weight": self.weight,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class NewsFact:
    """One news article, optionally tied to an asset."""

    asset_code: str
    title: str
    published_at: datetime
    source: str = ""
    summary: str = ""
    url: str = ""
    external_id: str = ""
    sentiment_score: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("NewsFact title cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "title": self.title,
            "summary": self.summary,
            "published_at": self.published_at.isoformat(),
            "url": self.url,
            "source": self.source,
            "external_id": self.external_id,
            "sentiment_score": self.sentiment_score,
            "extra": self.extra,
            "fetched_at": self.fetched_at.isoformat(),
        }


@dataclass(frozen=True)
class CapitalFlowFact:
    """Daily capital-flow breakdown for an asset."""

    asset_code: str
    flow_date: date
    main_net: float | None = None
    retail_net: float | None = None
    super_large_net: float | None = None
    large_net: float | None = None
    medium_net: float | None = None
    small_net: float | None = None
    source: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_code:
            raise ValueError("CapitalFlowFact.asset_code cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "flow_date": self.flow_date.isoformat(),
            "main_net": self.main_net,
            "retail_net": self.retail_net,
            "super_large_net": self.super_large_net,
            "large_net": self.large_net,
            "medium_net": self.medium_net,
            "small_net": self.small_net,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Raw payload audit value object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawAudit:
    """Immutable record of one raw provider response for audit/debugging."""

    provider_name: str
    capability: str
    request_params: dict[str, Any]
    status: str
    row_count: int = 0
    latency_ms: float | None = None
    error_message: str = ""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "capability": self.capability,
            "request_params": self.request_params,
            "status": self.status,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "error_message": self.error_message,
            "fetched_at": self.fetched_at.isoformat(),
            "extra": self.extra,
        }
