"""
Data Center — Domain Layer Protocols

Protocol interfaces that infrastructure implementations must satisfy.
Domain / application layers depend only on these abstractions.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol, runtime_checkable

from apps.data_center.domain.entities import (
    AssetMaster,
    CapitalFlowFact,
    ConnectionTestResult,
    DataProviderSettings,
    FinancialFact,
    FundNavFact,
    IndicatorCatalog,
    IndicatorUnitRule,
    MacroFact,
    NewsFact,
    PriceBar,
    ProviderConfig,
    ProviderHealthSnapshot,
    PublisherCatalog,
    QuoteSnapshot,
    RawAudit,
    SectorMembershipFact,
    ValuationFact,
)
from apps.data_center.domain.enums import DataCapability, FinancialPeriodType


@runtime_checkable
class ProviderConfigRepositoryProtocol(Protocol):
    """Persistence contract for provider configurations."""

    def list_all(self) -> list[ProviderConfig]: ...
    def get_by_id(self, provider_id: int) -> ProviderConfig | None: ...
    def get_by_name(self, name: str) -> ProviderConfig | None: ...
    def save(self, config: ProviderConfig) -> ProviderConfig: ...
    def delete(self, provider_id: int) -> None: ...
    def get_active_by_type(self, source_type: str) -> list[ProviderConfig]: ...


@runtime_checkable
class DataProviderSettingsRepositoryProtocol(Protocol):
    """Persistence contract for global provider settings (singleton)."""

    def load(self) -> DataProviderSettings: ...
    def save(self, settings: DataProviderSettings) -> DataProviderSettings: ...


@runtime_checkable
class ProviderProtocol(Protocol):
    """Contract that every data-provider adapter must implement."""

    def provider_name(self) -> str: ...
    def supports(self, capability: DataCapability) -> bool: ...


@runtime_checkable
class UnifiedDataProviderProtocol(ProviderProtocol, Protocol):
    """Unified multi-domain adapter contract used by Phase 3 sync use cases."""

    def fetch_macro_series(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MacroFact]: ...

    def fetch_price_history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]: ...

    def fetch_quote_snapshots(
        self,
        asset_codes: list[str],
    ) -> list[QuoteSnapshot]: ...

    def fetch_fund_nav(
        self,
        fund_code: str,
        start_date: date,
        end_date: date,
    ) -> list[FundNavFact]: ...

    def fetch_financials(
        self,
        asset_code: str,
        periods: int = 8,
    ) -> list[FinancialFact]: ...

    def fetch_valuations(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
    ) -> list[ValuationFact]: ...

    def fetch_sector_memberships(
        self,
        sector_code: str = "",
        sector_name: str = "",
        effective_date: date | None = None,
    ) -> list[SectorMembershipFact]: ...

    def fetch_news(
        self,
        asset_code: str,
        limit: int = 20,
    ) -> list[NewsFact]: ...

    def fetch_capital_flows(
        self,
        asset_code: str,
        period: str = "5d",
    ) -> list[CapitalFlowFact]: ...


@runtime_checkable
class RegistryProtocol(Protocol):
    """Contract for the unified source registry."""

    def register(self, provider: ProviderProtocol, priority: int = 100) -> None: ...

    def get_provider(
        self, capability: DataCapability
    ) -> ProviderProtocol | None: ...

    def get_providers(
        self, capability: DataCapability
    ) -> list[ProviderProtocol]: ...

    def call_with_failover(
        self,
        capability: DataCapability,
        fn: Any,
    ) -> Any: ...

    def record_success(
        self, provider_name: str, capability: DataCapability, latency_ms: float
    ) -> None: ...

    def record_failure(
        self, provider_name: str, capability: DataCapability
    ) -> None: ...

    def get_all_statuses(self) -> list[ProviderHealthSnapshot]: ...


@runtime_checkable
class ConnectionTesterProtocol(Protocol):
    """Contract for provider connectivity probes."""

    def test(self, config: ProviderConfig) -> ConnectionTestResult: ...


# ---------------------------------------------------------------------------
# Phase 2 — Master-data & fact-table repository protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class AssetRepositoryProtocol(Protocol):
    """Persistence contract for AssetMaster (security master table)."""

    def get_by_code(self, code: str) -> AssetMaster | None: ...
    def search(self, query: str, limit: int = 20) -> list[AssetMaster]: ...
    def upsert(self, asset: AssetMaster) -> AssetMaster: ...
    def list_by_exchange(self, exchange: str) -> list[AssetMaster]: ...


@runtime_checkable
class IndicatorCatalogRepositoryProtocol(Protocol):
    """Persistence contract for IndicatorCatalog definitions."""

    def get_by_code(self, code: str) -> IndicatorCatalog | None: ...
    def list_all(self) -> list[IndicatorCatalog]: ...
    def list_active(self) -> list[IndicatorCatalog]: ...
    def upsert(self, catalog: IndicatorCatalog) -> IndicatorCatalog: ...
    def delete(self, code: str) -> None: ...


@runtime_checkable
class PublisherCatalogRepositoryProtocol(Protocol):
    """Persistence contract for provenance publisher definitions."""

    def get_by_code(self, code: str) -> PublisherCatalog | None: ...
    def list_all(self) -> list[PublisherCatalog]: ...
    def list_active(self) -> list[PublisherCatalog]: ...
    def upsert(self, publisher: PublisherCatalog) -> PublisherCatalog: ...
    def delete(self, code: str) -> None: ...


@runtime_checkable
class IndicatorUnitRuleRepositoryProtocol(Protocol):
    """Persistence contract for macro indicator unit-governance rules."""

    def get_by_id(self, rule_id: int) -> IndicatorUnitRule | None: ...
    def list_by_indicator(self, indicator_code: str) -> list[IndicatorUnitRule]: ...
    def upsert(self, rule: IndicatorUnitRule) -> IndicatorUnitRule: ...
    def delete(self, rule_id: int) -> None: ...
    def resolve_active_rule(
        self,
        indicator_code: str,
        *,
        source_type: str = "",
        original_unit: str | None = None,
    ) -> IndicatorUnitRule | None: ...


@runtime_checkable
class MacroGovernanceRepositoryProtocol(Protocol):
    """Governance audit and repair contract for canonical macro facts."""

    def list_governed_indicator_codes(self, *, scope: str = "macro_console") -> list[str]: ...

    def list_sync_supported_indicator_codes(
        self,
        *,
        scope: str = "macro_console",
    ) -> set[str]: ...

    def build_snapshot(self, *, scope: str = "macro_console") -> dict[str, Any]: ...

    def canonicalize_sources(
        self,
        *,
        scope: str = "macro_console",
        indicator_codes: list[str] | None = None,
    ) -> dict[str, int]: ...

    def normalize_macro_fact_units(
        self,
        *,
        indicator_codes: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]: ...


@runtime_checkable
class MacroFactRepositoryProtocol(Protocol):
    """Persistence contract for MacroFact time-series."""

    def get_series(
        self,
        indicator_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[MacroFact]: ...

    def get_latest(self, indicator_code: str) -> MacroFact | None: ...
    def bulk_upsert(self, facts: list[MacroFact]) -> int: ...


@runtime_checkable
class PriceBarRepositoryProtocol(Protocol):
    """Persistence contract for OHLCV price bars."""

    def get_bars(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
    ) -> list[PriceBar]: ...

    def get_latest(self, asset_code: str) -> PriceBar | None: ...
    def bulk_upsert(self, bars: list[PriceBar]) -> int: ...


@runtime_checkable
class QuoteSnapshotRepositoryProtocol(Protocol):
    """Persistence contract for real-time / intraday quote snapshots."""

    def get_latest(self, asset_code: str) -> QuoteSnapshot | None: ...
    def bulk_upsert(self, quotes: list[QuoteSnapshot]) -> int: ...


@runtime_checkable
class FundNavRepositoryProtocol(Protocol):
    """Persistence contract for fund NAV facts."""

    def get_series(
        self,
        fund_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[FundNavFact]: ...

    def get_latest(self, fund_code: str) -> FundNavFact | None: ...
    def bulk_upsert(self, facts: list[FundNavFact]) -> int: ...


@runtime_checkable
class FinancialFactRepositoryProtocol(Protocol):
    """Persistence contract for financial statement facts."""

    def get_facts(
        self,
        asset_code: str,
        period_type: FinancialPeriodType | None = None,
        limit: int = 20,
    ) -> list[FinancialFact]: ...

    def get_latest(
        self, asset_code: str, period_type: FinancialPeriodType | None = None
    ) -> FinancialFact | None: ...

    def bulk_upsert(self, facts: list[FinancialFact]) -> int: ...


@runtime_checkable
class ValuationFactRepositoryProtocol(Protocol):
    """Persistence contract for daily valuation multiples."""

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[ValuationFact]: ...

    def get_latest(self, asset_code: str) -> ValuationFact | None: ...
    def bulk_upsert(self, facts: list[ValuationFact]) -> int: ...


@runtime_checkable
class SectorMembershipRepositoryProtocol(Protocol):
    """Persistence contract for sector / index constituent membership."""

    def get_members(
        self, sector_code: str, as_of: date | None = None
    ) -> list[SectorMembershipFact]: ...

    def get_sectors_for_asset(
        self, asset_code: str, as_of: date | None = None
    ) -> list[SectorMembershipFact]: ...

    def bulk_upsert(self, facts: list[SectorMembershipFact]) -> int: ...


@runtime_checkable
class NewsRepositoryProtocol(Protocol):
    """Persistence contract for news articles."""

    def get_recent(
        self,
        asset_code: str | None = None,
        limit: int = 50,
    ) -> list[NewsFact]: ...

    def bulk_insert(self, articles: list[NewsFact]) -> int: ...


@runtime_checkable
class CapitalFlowRepositoryProtocol(Protocol):
    """Persistence contract for capital-flow (main-force / retail) data."""

    def get_series(
        self,
        asset_code: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[CapitalFlowFact]: ...

    def get_latest(self, asset_code: str) -> CapitalFlowFact | None: ...
    def bulk_upsert(self, facts: list[CapitalFlowFact]) -> int: ...


@runtime_checkable
class RawAuditRepositoryProtocol(Protocol):
    """Persistence contract for raw-fetch audit log."""

    def log(self, audit: RawAudit) -> RawAudit: ...
    def get_recent(
        self,
        provider_name: str | None = None,
        capability: str | None = None,
        limit: int = 100,
    ) -> list[RawAudit]: ...
