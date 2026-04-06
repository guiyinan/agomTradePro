"""
Data Center — Application Layer DTOs

Input/output data-transfer objects for all use cases (Phase 1 + Phase 2).
Plain dataclasses — no ORM, no Django imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class CreateProviderRequest:
    """Input DTO for creating a new provider config."""

    name: str
    source_type: str
    is_active: bool = True
    priority: int = 100
    api_key: str = ""
    api_secret: str = ""
    http_url: str = ""
    api_endpoint: str = ""
    extra_config: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class UpdateProviderRequest:
    """Input DTO for updating an existing provider config (partial allowed)."""

    provider_id: int
    name: str | None = None
    source_type: str | None = None
    is_active: bool | None = None
    priority: int | None = None
    api_key: str | None = None
    api_secret: str | None = None
    http_url: str | None = None
    api_endpoint: str | None = None
    extra_config: dict[str, Any] | None = None
    description: str | None = None


@dataclass
class ProviderResponse:
    """Output DTO for a provider config."""

    id: int | None
    name: str
    source_type: str
    is_active: bool
    priority: int
    api_key: str
    api_secret: str
    http_url: str
    api_endpoint: str
    extra_config: dict[str, Any]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type,
            "is_active": self.is_active,
            "priority": self.priority,
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "http_url": self.http_url,
            "api_endpoint": self.api_endpoint,
            "extra_config": self.extra_config,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Phase 2 — Query DTOs
# ---------------------------------------------------------------------------


@dataclass
class ResolveAssetRequest:
    """Input DTO for resolving a ticker to a canonical AssetMaster record."""

    code: str
    source_type: str = ""  # hint for normalisation (e.g. "akshare")


@dataclass
class AssetResponse:
    """Output DTO for a resolved asset."""

    code: str
    name: str
    short_name: str
    asset_type: str
    exchange: str
    is_active: bool
    list_date: date | None
    sector: str
    industry: str
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "short_name": self.short_name,
            "asset_type": self.asset_type,
            "exchange": self.exchange,
            "is_active": self.is_active,
            "list_date": self.list_date.isoformat() if self.list_date else None,
            "sector": self.sector,
            "industry": self.industry,
            "currency": self.currency,
        }


@dataclass
class MacroSeriesRequest:
    """Input DTO for fetching a macro time-series."""

    indicator_code: str
    start: date | None = None
    end: date | None = None
    limit: int = 500
    source: str | None = None  # if None, return all sources


@dataclass
class MacroDataPoint:
    """Single macro time-series data point."""

    indicator_code: str
    reporting_period: date
    value: float
    unit: str
    source: str
    quality: str
    published_at: date | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_code": self.indicator_code,
            "reporting_period": self.reporting_period.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "quality": self.quality,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


@dataclass
class MacroSeriesResponse:
    """Output DTO for a macro time-series query."""

    indicator_code: str
    name_cn: str
    data: list[MacroDataPoint] = field(default_factory=list)
    total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_code": self.indicator_code,
            "name_cn": self.name_cn,
            "total": self.total,
            "data": [p.to_dict() for p in self.data],
        }


@dataclass
class PriceHistoryRequest:
    """Input DTO for fetching OHLCV price bars."""

    asset_code: str
    start: date | None = None
    end: date | None = None
    freq: str = "1d"
    adjustment: str = "none"
    limit: int = 500


@dataclass
class PriceBarResponse:
    """Output DTO for a single OHLCV bar."""

    asset_code: str
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    amount: float | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_code": self.asset_code,
            "bar_date": self.bar_date.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "source": self.source,
        }


@dataclass
class LatestQuoteRequest:
    """Input DTO for fetching the latest quote snapshot."""

    asset_code: str


@dataclass
class QuoteResponse:
    """Output DTO for a real-time quote snapshot."""

    asset_code: str
    snapshot_at: datetime
    current_price: float
    open: float | None
    high: float | None
    low: float | None
    prev_close: float | None
    volume: float | None
    source: str

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
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Phase 3 — Sync DTOs
# ---------------------------------------------------------------------------


@dataclass
class SyncMacroRequest:
    provider_id: int
    indicator_code: str
    start: date
    end: date


@dataclass
class SyncPriceRequest:
    provider_id: int
    asset_code: str
    start: date
    end: date


@dataclass
class SyncQuoteRequest:
    provider_id: int
    asset_codes: list[str]


@dataclass
class SyncFundNavRequest:
    provider_id: int
    fund_code: str
    start: date
    end: date


@dataclass
class SyncFinancialRequest:
    provider_id: int
    asset_code: str
    periods: int = 8


@dataclass
class SyncValuationRequest:
    provider_id: int
    asset_code: str
    start: date
    end: date


@dataclass
class SyncSectorMembershipRequest:
    provider_id: int
    sector_code: str = ""
    sector_name: str = ""
    effective_date: date | None = None


@dataclass
class SyncNewsRequest:
    provider_id: int
    asset_code: str
    limit: int = 20


@dataclass
class SyncCapitalFlowRequest:
    provider_id: int
    asset_code: str
    period: str = "5d"


@dataclass
class SyncResult:
    domain: str
    provider_name: str
    stored_count: int
    status: str
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "provider_name": self.provider_name,
            "stored_count": self.stored_count,
            "status": self.status,
            "error_message": self.error_message,
        }
