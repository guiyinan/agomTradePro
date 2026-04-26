"""Data center repository providers for application consumers."""

from __future__ import annotations

from apps.data_center.domain.entities import DataProviderSettings, ProviderConfig
from apps.data_center.infrastructure.provider_factory import UnifiedProviderFactory
from apps.data_center.infrastructure.providers import (
    AssetRepository,
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    IndicatorCatalogRepository,
    LegacyMacroSeriesRepository,
    MacroFactRepository,
    NewsRepository,
    ProviderConfigRepository,
    PriceBarRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
)
from apps.data_center.infrastructure.registries.source_registry import SourceRegistry


def get_macro_fact_repository() -> MacroFactRepository:
    """Return the default macro fact repository."""

    return MacroFactRepository()


def get_data_provider_settings_repository() -> DataProviderSettingsRepository:
    """Return the default data-provider settings repository."""

    return DataProviderSettingsRepository()


def get_provider_config_repository() -> ProviderConfigRepository:
    """Return the default provider-config repository."""

    return ProviderConfigRepository()


def get_asset_repository() -> AssetRepository:
    return AssetRepository()


def get_capital_flow_repository() -> CapitalFlowRepository:
    return CapitalFlowRepository()


def get_financial_fact_repository() -> FinancialFactRepository:
    return FinancialFactRepository()


def get_fund_nav_repository() -> FundNavRepository:
    return FundNavRepository()


def get_indicator_catalog_repository() -> IndicatorCatalogRepository:
    return IndicatorCatalogRepository()


def get_legacy_macro_series_repository() -> LegacyMacroSeriesRepository:
    return LegacyMacroSeriesRepository()


def get_price_bar_repository() -> PriceBarRepository:
    return PriceBarRepository()


def get_news_repository() -> NewsRepository:
    return NewsRepository()


def get_quote_snapshot_repository() -> QuoteSnapshotRepository:
    return QuoteSnapshotRepository()


def get_raw_audit_repository() -> RawAuditRepository:
    return RawAuditRepository()


def get_sector_membership_repository() -> SectorMembershipRepository:
    return SectorMembershipRepository()


def get_valuation_fact_repository() -> ValuationFactRepository:
    return ValuationFactRepository()


def build_unified_provider_factory() -> UnifiedProviderFactory:
    """Build the default unified provider factory."""

    return UnifiedProviderFactory(get_provider_config_repository())


def get_source_registry() -> SourceRegistry:
    """Return the module-level source registry."""

    from apps.data_center.application.registry_factory import get_registry

    return get_registry()


def refresh_source_registry() -> SourceRegistry:
    """Refresh and return the module-level source registry."""

    from apps.data_center.application.registry_factory import refresh_registry

    return refresh_registry()


def load_data_provider_settings() -> DataProviderSettings:
    """Load the singleton provider settings via the application boundary."""

    return get_data_provider_settings_repository().load()


def list_active_provider_configs() -> list[ProviderConfig]:
    """List active provider configs ordered by priority."""

    return get_provider_config_repository().list_active()


def run_data_center_connection_test(*args, **kwargs):
    """Run a data-center connection test via the infrastructure implementation."""

    from apps.data_center.infrastructure.connection_tester import run_connection_test

    return run_connection_test(*args, **kwargs)
