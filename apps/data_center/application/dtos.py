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


@dataclass
class CreateIndicatorCatalogRequest:
    """Input DTO for creating a macro indicator definition."""

    code: str
    name_cn: str
    name_en: str = ""
    description: str = ""
    category: str = ""
    default_period_type: str = "M"
    is_active: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class UpdateIndicatorCatalogRequest:
    """Input DTO for updating one macro indicator definition."""

    code: str
    name_cn: str | None = None
    name_en: str | None = None
    description: str | None = None
    category: str | None = None
    default_period_type: str | None = None
    is_active: bool | None = None
    extra: dict[str, Any] | None = None


@dataclass
class IndicatorCatalogResponse:
    """Output DTO for one macro indicator definition."""

    code: str
    name_cn: str
    name_en: str
    description: str
    category: str
    default_period_type: str
    is_active: bool
    extra: dict[str, Any]
    default_rule: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name_cn": self.name_cn,
            "name_en": self.name_en,
            "description": self.description,
            "category": self.category,
            "default_period_type": self.default_period_type,
            "is_active": self.is_active,
            "extra": self.extra,
            "default_rule": self.default_rule,
        }


@dataclass
class CreateIndicatorUnitRuleRequest:
    """Input DTO for creating one indicator unit rule."""

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


@dataclass
class UpdateIndicatorUnitRuleRequest:
    """Input DTO for updating one indicator unit rule."""

    rule_id: int
    indicator_code: str
    source_type: str | None = None
    dimension_key: str | None = None
    original_unit: str | None = None
    storage_unit: str | None = None
    display_unit: str | None = None
    multiplier_to_storage: float | None = None
    is_active: bool | None = None
    priority: int | None = None
    description: str | None = None


@dataclass
class IndicatorUnitRuleResponse:
    """Output DTO for one indicator unit rule."""

    id: int | None
    indicator_code: str
    source_type: str
    dimension_key: str
    original_unit: str
    storage_unit: str
    display_unit: str
    multiplier_to_storage: float
    is_active: bool
    priority: int
    description: str

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
    display_value: float
    display_unit: str
    original_unit: str
    source: str
    quality: str
    published_at: date | None
    age_days: int
    is_stale: bool
    freshness_status: str
    decision_grade: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicator_code": self.indicator_code,
            "reporting_period": self.reporting_period.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "display_value": self.display_value,
            "display_unit": self.display_unit,
            "original_unit": self.original_unit,
            "source": self.source,
            "quality": self.quality,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "age_days": self.age_days,
            "is_stale": self.is_stale,
            "freshness_status": self.freshness_status,
            "decision_grade": self.decision_grade,
        }


@dataclass
class MacroSeriesResponse:
    """Output DTO for a macro time-series query."""

    indicator_code: str
    name_cn: str
    period_type: str
    data: list[MacroDataPoint] = field(default_factory=list)
    total: int = 0
    data_source: str = "none"
    freshness_status: str = "missing"
    decision_grade: str = "blocked"
    must_not_use_for_decision: bool = True
    blocked_reason: str = ""
    latest_reporting_period: date | None = None
    latest_published_at: date | None = None
    latest_quality: str = ""

    def to_dict(self) -> dict[str, Any]:
        contract = {
            "data_source": self.data_source,
            "freshness_status": self.freshness_status,
            "decision_grade": self.decision_grade,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reason": self.blocked_reason,
            "latest_reporting_period": (
                self.latest_reporting_period.isoformat() if self.latest_reporting_period else None
            ),
            "latest_published_at": (
                self.latest_published_at.isoformat() if self.latest_published_at else None
            ),
            "latest_quality": self.latest_quality,
        }
        return {
            "indicator_code": self.indicator_code,
            "name_cn": self.name_cn,
            "period_type": self.period_type,
            "total": self.total,
            "data": [p.to_dict() for p in self.data],
            "data_source": self.data_source,
            "freshness_status": self.freshness_status,
            "decision_grade": self.decision_grade,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reason": self.blocked_reason,
            "latest_reporting_period": (
                self.latest_reporting_period.isoformat() if self.latest_reporting_period else None
            ),
            "latest_published_at": (
                self.latest_published_at.isoformat() if self.latest_published_at else None
            ),
            "latest_quality": self.latest_quality,
            "contract": contract,
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
    max_age_hours: float = 4.0


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
    age_minutes: int
    is_stale: bool
    freshness_status: str
    must_not_use_for_decision: bool
    blocked_reason: str
    max_age_hours: float

    def to_dict(self) -> dict[str, Any]:
        contract = {
            "snapshot_at": self.snapshot_at.isoformat(),
            "age_minutes": self.age_minutes,
            "is_stale": self.is_stale,
            "freshness_status": self.freshness_status,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reason": self.blocked_reason,
            "max_age_hours": self.max_age_hours,
        }
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
            "age_minutes": self.age_minutes,
            "is_stale": self.is_stale,
            "freshness_status": self.freshness_status,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reason": self.blocked_reason,
            "max_age_hours": self.max_age_hours,
            "contract": contract,
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


# ---------------------------------------------------------------------------
# Decision reliability repair DTOs
# ---------------------------------------------------------------------------


@dataclass
class DecisionReliabilityRepairRequest:
    """Input DTO for repairing decision-grade data dependencies."""

    target_date: date | None = None
    portfolio_id: int | None = None
    asset_codes: list[str] = field(default_factory=list)
    macro_indicator_codes: list[str] = field(default_factory=list)
    strict: bool = True
    quote_max_age_hours: float = 4.0
    macro_lookback_days: int = 180
    price_lookback_days: int = 30
    repair_pulse: bool = True
    repair_alpha: bool = True


@dataclass
class DecisionReliabilitySection:
    """Uniform readiness section used by the repair report."""

    status: str
    must_not_use_for_decision: bool
    blocked_reasons: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reasons": self.blocked_reasons,
            "details": self.details,
        }


@dataclass
class DecisionReliabilityRepairReport:
    """Output DTO for the full data reliability repair workflow."""

    target_date: date
    portfolio_id: int | None
    macro_status: DecisionReliabilitySection
    quote_status: DecisionReliabilitySection
    pulse_status: DecisionReliabilitySection
    alpha_status: DecisionReliabilitySection
    provider_bootstrap: dict[str, Any] = field(default_factory=dict)

    @property
    def must_not_use_for_decision(self) -> bool:
        return any(
            section.must_not_use_for_decision
            for section in (
                self.macro_status,
                self.quote_status,
                self.pulse_status,
                self.alpha_status,
            )
        )

    @property
    def blocked_reasons(self) -> list[str]:
        reasons: list[str] = []
        for section in (
            self.macro_status,
            self.quote_status,
            self.pulse_status,
            self.alpha_status,
        ):
            reasons.extend(section.blocked_reasons)
        return reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date.isoformat(),
            "portfolio_id": self.portfolio_id,
            "macro_status": self.macro_status.to_dict(),
            "quote_status": self.quote_status.to_dict(),
            "pulse_status": self.pulse_status.to_dict(),
            "alpha_status": self.alpha_status.to_dict(),
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "blocked_reasons": self.blocked_reasons,
            "provider_bootstrap": self.provider_bootstrap,
        }
