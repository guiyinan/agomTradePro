"""Data Center composition root for repositories and provider runtime."""

from __future__ import annotations

from typing import Any

from apps.data_center.domain.entities import (
    DataProviderSettings,
    ProviderConfig,
)
from apps.data_center.infrastructure.cache_warmup_queries import (
    MacroFactCacheWarmupRepository,
)
from apps.data_center.infrastructure.diagnostic_queries import DataCenterDiagnosticRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.repositories import (
    AssetRepository,
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
    MacroFactRepository,
    MacroGovernanceRepository,  # noqa: F401
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
    NewsRepository,
    PriceBarRepository,
    ProductionCoverageUniverseConfigRepository,
    ProviderConfigRepository,
    PublisherCatalogRepository,
    QuoteSnapshotRepository,
    RawAuditRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
)


def get_macro_fact_repository() -> MacroFactRepository:
    """Return the default macro fact repository."""

    return MacroFactRepository()


def get_macro_fact_cache_warmup_repository() -> MacroFactCacheWarmupRepository:
    """Return the macro fact cache-warmup query repository."""

    return MacroFactCacheWarmupRepository()


def get_data_center_diagnostic_repository() -> DataCenterDiagnosticRepository:
    """Return the data-center diagnostic query repository."""

    return DataCenterDiagnosticRepository()


def get_data_provider_settings_repository() -> DataProviderSettingsRepository:
    """Return the default data-provider settings repository."""

    return DataProviderSettingsRepository()


def get_production_coverage_universe_config_repository() -> (
    ProductionCoverageUniverseConfigRepository
):
    """Return the production coverage universe config repository."""

    return ProductionCoverageUniverseConfigRepository()


def get_provider_config_repository() -> ProviderConfigRepository:
    """Return the default provider-config repository."""

    return ProviderConfigRepository()


def get_asset_repository() -> AssetRepository:
    return AssetRepository()


def get_capital_flow_repository() -> CapitalFlowRepository:
    return CapitalFlowRepository()


def get_market_thermometer_config_repository() -> MarketThermometerConfigRepository:
    return MarketThermometerConfigRepository()


def get_market_thermometer_user_override_repository() -> MarketThermometerUserOverrideRepository:
    return MarketThermometerUserOverrideRepository()


def get_market_thermometer_snapshot_repository() -> MarketThermometerSnapshotRepository:
    return MarketThermometerSnapshotRepository()


def get_financial_fact_repository() -> FinancialFactRepository:
    return FinancialFactRepository()


def get_fund_nav_repository() -> FundNavRepository:
    return FundNavRepository()


def get_indicator_catalog_repository() -> IndicatorCatalogRepository:
    return IndicatorCatalogRepository()


def get_publisher_catalog_repository() -> PublisherCatalogRepository:
    return PublisherCatalogRepository()


def get_indicator_unit_rule_repository() -> IndicatorUnitRuleRepository:
    return IndicatorUnitRuleRepository()


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


def get_akshare_module() -> Any:
    """Return the shared AKShare module via the data-center boundary."""

    from apps.data_center.infrastructure.legacy_sdk_bridge import (
        get_akshare_module as _get_akshare_module,
    )

    return _get_akshare_module()


def fetch_tushare_historical_prices(
    *,
    asset_code: str,
    start_date: str,
    end_date: str,
) -> list[Any]:
    """Fetch historical bars through the data-center Tushare gateway."""

    from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway

    return TushareGateway().get_historical_prices(
        asset_code=asset_code,
        start_date=start_date,
        end_date=end_date,
    )


def fetch_akshare_eastmoney_historical_prices(
    *,
    asset_code: str,
    start_date: str,
    end_date: str,
) -> list[Any]:
    """Fetch historical bars through the data-center AKShare EastMoney gateway."""

    from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
        AKShareEastMoneyGateway,
    )

    return AKShareEastMoneyGateway().get_historical_prices(
        asset_code=asset_code,
        start_date=start_date,
        end_date=end_date,
    )


def get_provider_registry() -> ProviderRegistry:
    """Return the canonical configured provider registry."""

    from apps.data_center.provider_runtime import get_registry

    return get_registry()


def build_provider_registry_for_repo(
    provider_repo: ProviderConfigRepository,
) -> ProviderRegistry:
    """Build an isolated provider registry for an explicit repository."""

    return ProviderRegistry.from_repository(provider_repo)


def refresh_provider_registry() -> ProviderRegistry:
    """Refresh and return the process-wide canonical provider registry."""

    from apps.data_center.provider_runtime import refresh_registry

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
