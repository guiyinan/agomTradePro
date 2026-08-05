"""Data Center composition root for repositories and provider runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from apps.data_center.application.control_plane import RollbackCanonicalPublicationUseCase
from apps.data_center.application.pit_use_cases import (
    BuildPITManifestUseCase,
    QueryPITManifestUseCase,
)
from apps.data_center.application.research_data_foundation import (
    ResearchDataFoundationFacade,
)
from apps.data_center.domain.entities import (
    DataProviderSettings,
    ProviderConfig,
)
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.infrastructure.cache_warmup_queries import (
    MacroFactCacheWarmupRepository,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DataOwnerRegistryRepository,
    DatasetContractRepository,
    ProviderBindingRepository,
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
    QuarantineRepository,
    SyncBatchRepository,
    SyncCheckpointRepository,
    SyncRunRepository,
)
from apps.data_center.infrastructure.diagnostic_queries import DataCenterDiagnosticRepository
from apps.data_center.infrastructure.macro_projection_repository import MacroProjectionRepository
from apps.data_center.infrastructure.pit_repository import PITManifestRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.raw_landing_repositories import (
    RawLandingRepository,
    SchemaFingerprintRepository,
)
from apps.data_center.infrastructure.repositories import (
    AssetRepository,
    CapitalFlowRepository,
    DataProviderSettingsRepository,
    FinancialFactRepository,
    FundNavRepository,
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
    MacroFactRepository,
    MacroGovernanceRepository,
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
    ReconciliationEvidenceRepository,
    SectorMembershipRepository,
    ValuationFactRepository,
)
from apps.data_center.infrastructure.research_data_foundation_repository import (
    ResearchDataFoundationRepository,
)
from apps.data_center.infrastructure.retention_repositories import (
    ArchiveManifestRepository,
    RetentionPolicyRepository,
    RetentionRunRepository,
    StorageHoldRepository,
)

__all__ = [
    "AssetRepository",
    "ArchiveManifestRepository",
    "CapitalFlowRepository",
    "CanonicalPublicationRepository",
    "DataCenterDiagnosticRepository",
    "DataOwnerRegistryRepository",
    "DataProviderSettingsRepository",
    "DatasetContractRepository",
    "FinancialFactRepository",
    "FundNavRepository",
    "IndicatorCatalogRepository",
    "IndicatorUnitRuleRepository",
    "MacroFactCacheWarmupRepository",
    "MacroFactRepository",
    "MacroProjectionRepository",
    "MacroGovernanceRepository",
    "MarketThermometerConfigRepository",
    "MarketThermometerSnapshotRepository",
    "MarketThermometerUserOverrideRepository",
    "NewsRepository",
    "PITManifestRepository",
    "PriceBarRepository",
    "ProductionCoverageUniverseConfigRepository",
    "ProviderConfigRepository",
    "ProviderBindingRepository",
    "ProviderRegistry",
    "PublisherCatalogRepository",
    "PublicationPolicyRepository",
    "QuoteSnapshotRepository",
    "QuarantineRepository",
    "RawAuditRepository",
    "ReconciliationEvidenceRepository",
    "RawLandingRepository",
    "ResearchDataFoundationRepository",
    "RetentionPolicyRepository",
    "RetentionRunRepository",
    "SectorMembershipRepository",
    "SchemaFingerprintRepository",
    "SyncBatchRepository",
    "SyncCheckpointRepository",
    "SyncRunRepository",
    "StorageHoldRepository",
    "ValuationFactRepository",
    "build_provider_registry_for_repo",
    "build_tushare_client",
    "backfill_asset_master_codes",
    "fetch_akshare_eastmoney_historical_prices",
    "fetch_tushare_historical_prices",
    "get_akshare_module",
    "get_akshare_eastmoney_gateway",
    "get_asset_repository",
    "get_archive_manifest_repository",
    "get_canonical_publication_repository",
    "get_rollback_canonical_publication_use_case",
    "get_capital_flow_repository",
    "get_data_center_diagnostic_repository",
    "get_data_owner_registry_repository",
    "get_data_provider_settings_repository",
    "get_dataset_contract_repository",
    "get_financial_fact_repository",
    "get_fund_nav_repository",
    "get_indicator_catalog_repository",
    "get_indicator_unit_rule_repository",
    "get_macro_fact_cache_warmup_repository",
    "get_macro_fact_repository",
    "get_macro_projection_repository",
    "get_market_thermometer_config_repository",
    "get_market_thermometer_snapshot_repository",
    "get_market_thermometer_user_override_repository",
    "get_news_repository",
    "get_price_bar_repository",
    "get_production_coverage_universe_config_repository",
    "get_provider_config_repository",
    "get_provider_binding_repository",
    "get_provider_registry",
    "get_publisher_catalog_repository",
    "get_publication_policy_repository",
    "get_quote_snapshot_repository",
    "get_quarantine_repository",
    "get_raw_audit_repository",
    "get_reconciliation_evidence_repository",
    "get_raw_landing_repository",
    "get_retention_policy_repository",
    "get_retention_run_repository",
    "get_sector_membership_repository",
    "get_schema_fingerprint_repository",
    "get_sync_batch_repository",
    "get_sync_checkpoint_repository",
    "get_sync_run_repository",
    "get_storage_hold_repository",
    "get_valuation_fact_repository",
    "list_active_provider_configs",
    "load_data_provider_settings",
    "make_build_pit_manifest_use_case",
    "make_manifest_bound_pit_data_view",
    "make_query_pit_manifest_use_case",
    "make_research_data_foundation_facade",
    "refresh_provider_registry",
    "run_data_center_connection_test",
]


def get_macro_fact_repository() -> MacroFactRepository:
    """Return the default macro fact repository."""

    return MacroFactRepository()


def get_macro_projection_repository() -> MacroProjectionRepository:
    """Return the Data Center-owned legacy macro projection repository."""

    return MacroProjectionRepository()


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


def get_dataset_contract_repository() -> DatasetContractRepository:
    """Return the persisted Dataset Contract repository."""

    return DatasetContractRepository()


def get_provider_binding_repository() -> ProviderBindingRepository:
    """Return the persisted provider-binding repository."""

    return ProviderBindingRepository()


def get_publication_policy_repository() -> PublicationPolicyRepository:
    """Return the persisted publication-policy repository."""

    return PublicationPolicyRepository()


def get_data_owner_registry_repository() -> DataOwnerRegistryRepository:
    """Return the persisted dataset ownership repository."""

    return DataOwnerRegistryRepository()


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


def get_raw_landing_repository() -> RawLandingRepository:
    """Return the redacted raw payload repository."""

    return RawLandingRepository()


def get_schema_fingerprint_repository() -> SchemaFingerprintRepository:
    """Return the provider schema evidence repository."""

    return SchemaFingerprintRepository()


def get_retention_policy_repository() -> RetentionPolicyRepository:
    """Return dataset retention policy repository."""

    return RetentionPolicyRepository()


def get_storage_hold_repository() -> StorageHoldRepository:
    """Return storage hold repository."""

    return StorageHoldRepository()


def get_retention_run_repository() -> RetentionRunRepository:
    """Return append-only retention run evidence repository."""

    return RetentionRunRepository()


def get_archive_manifest_repository() -> ArchiveManifestRepository:
    """Return archive manifest repository."""

    return ArchiveManifestRepository()


def get_reconciliation_evidence_repository() -> ReconciliationEvidenceRepository:
    """Return the shadow-reconciliation evidence repository."""

    return ReconciliationEvidenceRepository()


def get_sector_membership_repository() -> SectorMembershipRepository:
    return SectorMembershipRepository()


def get_valuation_fact_repository() -> ValuationFactRepository:
    return ValuationFactRepository()


def get_sync_run_repository() -> SyncRunRepository:
    """Return the ingestion run repository."""

    return SyncRunRepository()


def get_sync_batch_repository() -> SyncBatchRepository:
    """Return the ingestion batch repository."""

    return SyncBatchRepository()


def get_sync_checkpoint_repository() -> SyncCheckpointRepository:
    """Return the resumable checkpoint repository."""

    return SyncCheckpointRepository()


def get_quarantine_repository() -> QuarantineRepository:
    """Return the rejected-payload repository."""

    return QuarantineRepository()


def get_canonical_publication_repository() -> CanonicalPublicationRepository:
    """Return the canonical publication repository."""

    return CanonicalPublicationRepository()


def get_rollback_canonical_publication_use_case() -> RollbackCanonicalPublicationUseCase:
    """Return the explicit canonical publication rollback use case."""

    return RollbackCanonicalPublicationUseCase(get_canonical_publication_repository())


def get_akshare_module() -> Any:
    """Return the shared AKShare module via the data-center boundary."""

    from apps.data_center.infrastructure.legacy_sdk_bridge import (
        get_akshare_module as _get_akshare_module,
    )

    return _get_akshare_module()


def get_akshare_eastmoney_gateway() -> object:
    """Return the Data Center-owned EastMoney gateway for migration adapters."""

    from apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway import (
        AKShareEastMoneyGateway,
    )

    return AKShareEastMoneyGateway()


def backfill_asset_master_codes(
    asset_codes: list[str],
    *,
    include_remote: bool = True,
) -> object:
    """Backfill canonical asset identities behind the Data Center composition root."""

    from apps.data_center.infrastructure.asset_master_backfill import AssetMasterBackfillService
    from core.integration.asset_master_sources import build_legacy_asset_master_source

    return AssetMasterBackfillService(
        source_provider=build_legacy_asset_master_source()
    ).backfill_codes(
        asset_codes,
        include_remote=include_remote,
    )


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
    provider_repo: ProviderConfigRepositoryProtocol,
) -> ProviderRegistry:
    """Build an isolated provider registry for an explicit repository."""

    return ProviderRegistry.from_repository(provider_repo)


def build_tushare_client(*, token: str | None = None, http_url: str | None = None) -> object:
    """Build the Data Center-owned Tushare transport behind the composition root."""

    from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client

    return create_tushare_pro_client(token=token, http_url=http_url)


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


def run_data_center_connection_test(*args: Any, **kwargs: Any) -> Any:
    """Run a data-center connection test via the infrastructure implementation."""

    from apps.data_center.infrastructure.connection_tester import run_connection_test

    runner = cast(Callable[..., Any], run_connection_test)
    return runner(*args, **kwargs)


def make_build_pit_manifest_use_case() -> BuildPITManifestUseCase:
    """Compose the canonical PIT manifest writer."""

    return BuildPITManifestUseCase(PITManifestRepository())


def make_query_pit_manifest_use_case() -> QueryPITManifestUseCase:
    """Compose the canonical PIT manifest reader."""

    return QueryPITManifestUseCase(PITManifestRepository())


def make_research_data_foundation_facade() -> ResearchDataFoundationFacade:
    """Compose the governed R1/R2 data-foundation application facade."""

    return ResearchDataFoundationFacade(ResearchDataFoundationRepository())


def make_manifest_bound_pit_data_view(manifest_id: str):  # type: ignore[no-untyped-def]
    """Return a verified PIT reader constrained to one immutable manifest."""

    from apps.data_center.infrastructure.pit_repository import ManifestBoundPITDataView

    return ManifestBoundPITDataView(manifest_id)
