"""Data Center composition root for repositories and provider runtime."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.db import transaction

from apps.data_center.application.control_plane import RollbackCanonicalPublicationUseCase
from apps.data_center.application.current_fact_remediation import (
    CompletedSessionPriceBarUseCase,
    CoreCurrentFactRefreshUseCase,
    FinancialAvailabilityBackfillUseCase,
)
from apps.data_center.application.current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationDataset,
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_valuation_sync import (
    SyncCurrentValuationBatchUseCase,
)
from apps.data_center.application.data_chain_replay import ReplayDataChainUseCase
from apps.data_center.application.decision_read_audit import (
    RecordPublicationDecisionReadUseCase,
)
from apps.data_center.application.macro_publication import PublishMacroBatchUseCase
from apps.data_center.application.pit_use_cases import (
    BuildPITManifestUseCase,
    QueryPITManifestUseCase,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_sync import (
    PublishPriceBarBatchUseCase,
    PublishQuoteSnapshotBatchUseCase,
)
from apps.data_center.application.reconciliation import RecordReconciliationEvidenceUseCase
from apps.data_center.application.repair_run_replay import ReplayRepairRunUseCase
from apps.data_center.application.research_data_foundation import (
    ResearchDataFoundationFacade,
)
from apps.data_center.application.sync_identity import SyncExecutionIdentityIssuer
from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataCenterSyncUnitOfWorkParticipant,
    DataRepairAuditWriter,
)
from apps.data_center.application.sync_use_cases import (
    MacroFailoverPolicyProvider,
    SyncFinancialUseCase,
    SyncMacroUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
)
from apps.data_center.domain.control_plane import SyncBatch, SyncCheckpoint, SyncRun
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)
from apps.data_center.infrastructure.archive_repositories import (
    ArchiveCandidateRepository,
    ArchiveCapacityGuard,
    ArchiveCoverageGateway,
)
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncClock,
    DjangoDataCenterSyncUnitOfWork,
    DjangoRepairRunIdentityUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
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
    SyncExecutionIdentityRepository,
    SyncRunRepository,
)
from apps.data_center.infrastructure.data_chain_replay_evidence import (
    DjangoReplayFactEvidenceReader,
)
from apps.data_center.infrastructure.diagnostic_queries import DataCenterDiagnosticRepository
from apps.data_center.infrastructure.macro_failover_policy import (
    ConfigCenterMacroFailoverPolicyProvider,
)
from apps.data_center.infrastructure.macro_projection_repository import MacroProjectionRepository
from apps.data_center.infrastructure.pit_repository import PITManifestRepository
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.infrastructure.raw_archive_store import FilesystemRawArchiveStore
from apps.data_center.infrastructure.raw_landing_repositories import (
    RawLandingRepository,
    SchemaFingerprintRepository,
)
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    DjangoReconciliationEvidenceUnitOfWork,
)
from apps.data_center.infrastructure.repositories import (
    AssetRepository,
    CapitalFlowRepository,
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
    RetentionPlanRepository,
    RetentionPolicyRepository,
    RetentionRunRepository,
    StorageHoldRepository,
)
from apps.data_center.infrastructure.rss_gateway import (
    RSSGatewayError,
    fetch_rss_feed,
    probe_rss_feed,
)

__all__ = [
    "AssetRepository",
    "ArchiveManifestRepository",
    "ArchiveCandidateRepository",
    "ArchiveCapacityGuard",
    "ArchiveCoverageGateway",
    "CapitalFlowRepository",
    "CanonicalPublicationRepository",
    "DataCenterDiagnosticRepository",
    "DataOwnerRegistryRepository",
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
    "make_macro_failover_policy_provider",
    "make_data_chain_replay_use_case",
    "make_core_current_fact_refresh_use_case",
    "make_core_current_publication_rebuild_use_case",
    "make_repair_run_replay_use_case",
    "make_publication_decision_read_recorder",
    "make_reconciliation_evidence_recorder",
    "make_repair_run_audit_dependencies",
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
    "RSSGatewayError",
    "ResearchDataFoundationRepository",
    "RetentionPolicyRepository",
    "RetentionPlanRepository",
    "RetentionRunRepository",
    "SectorMembershipRepository",
    "SchemaFingerprintRepository",
    "SyncBatchRepository",
    "SyncCheckpointRepository",
    "SyncExecutionIdentityRepository",
    "RepairRunAuditDependencies",
    "SyncRunRepository",
    "persist_sync_control_plane_snapshot",
    "StorageHoldRepository",
    "ValuationFactRepository",
    "build_provider_registry_for_repo",
    "build_tushare_client",
    "backfill_asset_master_codes",
    "get_alpha_price_coverage_sync_service",
    "fetch_akshare_eastmoney_historical_prices",
    "fetch_rss_feed",
    "probe_rss_feed",
    "fetch_tushare_historical_prices",
    "get_akshare_module",
    "get_akshare_eastmoney_gateway",
    "get_asset_repository",
    "get_archive_manifest_repository",
    "get_archive_candidate_repository",
    "get_archive_capacity_guard",
    "get_archive_coverage_gateway",
    "get_canonical_publication_repository",
    "get_rollback_canonical_publication_use_case",
    "get_capital_flow_repository",
    "get_data_center_diagnostic_repository",
    "get_data_owner_registry_repository",
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
    "get_raw_archive_store",
    "get_retention_policy_repository",
    "get_retention_plan_repository",
    "get_retention_run_repository",
    "get_sector_membership_repository",
    "get_schema_fingerprint_repository",
    "get_sync_batch_repository",
    "get_sync_checkpoint_repository",
    "get_sync_run_repository",
    "get_storage_hold_repository",
    "get_valuation_fact_repository",
    "list_active_provider_configs",
    "make_build_pit_manifest_use_case",
    "make_manifest_bound_pit_data_view",
    "make_query_pit_manifest_use_case",
    "make_research_data_foundation_facade",
    "make_system_audited_sync_macro_use_case",
    "make_system_audited_sync_price_use_case",
    "make_system_audited_sync_quote_use_case",
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


def resolve_canonical_asset_names(codes: list[str]) -> dict[str, str]:
    """Resolve display names from canonical AssetMaster rows without hydration."""

    repository = get_asset_repository()
    resolved: dict[str, str] = {}
    for raw_code in codes:
        code = str(raw_code or "").strip().upper()
        if not code or code in resolved:
            continue
        asset = repository.get_by_code(code)
        if asset is None or not asset.is_active:
            continue
        name = str(asset.short_name or asset.name or "").strip()
        if name:
            resolved[code] = name
    return resolved


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


def get_retention_plan_repository() -> RetentionPlanRepository:
    """Return the exact-member retention plan repository."""

    return RetentionPlanRepository()


def get_storage_hold_repository() -> StorageHoldRepository:
    """Return storage hold repository."""

    return StorageHoldRepository()


def get_retention_run_repository() -> RetentionRunRepository:
    """Return append-only retention run evidence repository."""

    return RetentionRunRepository()


def get_archive_manifest_repository() -> ArchiveManifestRepository:
    """Return archive manifest repository."""

    return ArchiveManifestRepository()


def _configured_archive_root() -> Path:
    configured = str(getattr(settings, "DATA_CENTER_ARCHIVE_ROOT", "") or "").strip()
    if not configured:
        raise RuntimeError("data_center_archive_root_not_configured")
    return Path(configured)


def get_raw_archive_store() -> FilesystemRawArchiveStore:
    """Return the configured cold archive store or fail closed."""

    encryption_key = str(getattr(settings, "DATA_CENTER_ARCHIVE_ENCRYPTION_KEY", "") or "").strip()
    encryption_key_version = str(
        getattr(settings, "DATA_CENTER_ARCHIVE_ENCRYPTION_KEY_VERSION", "") or ""
    ).strip()
    if not encryption_key or not encryption_key_version:
        raise RuntimeError("data_center_archive_encryption_not_configured")
    return FilesystemRawArchiveStore(
        _configured_archive_root(),
        encryption_key=encryption_key.encode("ascii"),
        encryption_key_ref="env:DATA_CENTER_ARCHIVE_ENCRYPTION_KEY",
        encryption_key_version=encryption_key_version,
    )


def get_archive_candidate_repository() -> ArchiveCandidateRepository:
    """Return the unarchived RawPayload candidate reader."""

    return ArchiveCandidateRepository()


def get_archive_capacity_guard() -> ArchiveCapacityGuard:
    """Return the Config Center-backed projected archive capacity gate."""

    return ArchiveCapacityGuard(_configured_archive_root())


def get_archive_coverage_gateway() -> ArchiveCoverageGateway:
    """Return the exact DB-and-byte retention deletion gate."""

    return ArchiveCoverageGateway(
        get_archive_manifest_repository(),
        get_raw_archive_store(),
    )


def get_reconciliation_evidence_repository() -> ReconciliationEvidenceRepository:
    """Return the shadow-reconciliation evidence repository."""

    return ReconciliationEvidenceRepository()


def make_reconciliation_evidence_recorder(
    *, environment: str = "production", using: str = "default"
) -> RecordReconciliationEvidenceUseCase:
    """Compose same-transaction reconciliation evidence and conflict audit."""

    from core.integration.data_center_audit import get_data_conflict_audit_writer

    repository = ReconciliationEvidenceRepository(using=using)
    audit_writer = get_data_conflict_audit_writer(
        environment=environment,
        using=using,
    )
    return RecordReconciliationEvidenceUseCase(
        repository,
        audit_writer=audit_writer,
        unit_of_work=DjangoReconciliationEvidenceUnitOfWork(
            repository,
            audit_writer,
            using=using,
        ),
        clock=DjangoDataCenterSyncClock(),
    )


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


def persist_sync_control_plane_snapshot(
    run: SyncRun,
    batch: SyncBatch,
    checkpoint: SyncCheckpoint,
) -> None:
    """Persist one run, batch, and checkpoint as an atomic snapshot.

    The transaction belongs to this composition root so application tasks
    remain independent of Django transaction primitives while the three
    repositories still share one durable commit boundary.
    """

    with transaction.atomic():
        get_sync_run_repository().save(run)
        get_sync_batch_repository().save(batch)
        get_sync_checkpoint_repository().save(checkpoint)


def get_quarantine_repository() -> QuarantineRepository:
    """Return the rejected-payload repository."""

    return QuarantineRepository()


def get_canonical_publication_repository() -> CanonicalPublicationRepository:
    """Return the canonical publication repository."""

    return CanonicalPublicationRepository()


def make_core_current_publication_rebuild_use_case(
    *,
    created_by: str = "ops.current_publication_rebuild",
) -> CoreCurrentPublicationRebuildUseCase:
    """Compose the atomic active-universe publication rebuild workflow."""

    publication_repository = CanonicalPublicationRepository()
    policy_repository = PublicationPolicyRepository()
    specifications = (
        (
            CurrentPublicationDataset(
                dataset_key="equity.quote.snapshot",
                fact_table="data_center_quote_snapshot",
                created_by=created_by,
            ),
            QuoteSnapshotRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.price.bar",
                fact_table="data_center_price_bar",
                created_by=created_by,
            ),
            PriceBarRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.valuation.fact",
                fact_table="data_center_valuation_fact",
                created_by=created_by,
            ),
            ValuationFactRepository(),
        ),
        (
            CurrentPublicationDataset(
                dataset_key="equity.financial.fact",
                fact_table="data_center_financial_fact",
                created_by=created_by,
            ),
            FinancialFactRepository(),
        ),
    )
    rebuilders = tuple(
        CurrentPublicationRebuildUseCase(
            dataset=dataset,
            candidate_repository=repository,
            publication_repository=publication_repository,
            policy_repository=policy_repository,
        )
        for dataset, repository in specifications
    )
    return CoreCurrentPublicationRebuildUseCase(
        rebuilders=rebuilders,
        transaction=transaction.atomic,
    )


def make_core_current_fact_refresh_use_case(
    *,
    source_type: str,
    created_by: str = "ops.current_fact_refresh",
) -> CoreCurrentFactRefreshUseCase:
    """Compose a fact-only provider refresh followed by atomic publication."""

    normalized_source = source_type.strip().lower()
    if not normalized_source:
        raise ValueError("source_type cannot be empty")
    provider_repository = ProviderConfigRepository()
    providers = provider_repository.get_active_by_type(normalized_source)
    provider = providers[0] if providers else None
    if provider is None or provider.id is None:
        raise ValueError(f"No active provider is configured for {normalized_source}")

    provider_registry = build_provider_registry_for_repo(provider_repository)
    financial_repository = FinancialFactRepository()
    price_repository = PriceBarRepository()
    quote_repository = QuoteSnapshotRepository()
    raw_audit_repository = RawAuditRepository()
    return CoreCurrentFactRefreshUseCase(
        provider_id=int(provider.id),
        quote_sync=make_system_audited_sync_quote_use_case(
            provider_repository=provider_repository,
            provider_registry=provider_registry,
            publish_current=False,
        ),
        price_sync=make_system_audited_sync_price_use_case(
            provider_repository=provider_repository,
            provider_registry=provider_registry,
            publish_current=False,
        ),
        valuation_sync=SyncCurrentValuationBatchUseCase(
            provider_repo=provider_repository,
            provider_registry=provider_registry,
            fact_repo=ValuationFactRepository(),
            raw_audit_repo=raw_audit_repository,
            publication_publisher=None,
        ),
        financial_sync=SyncFinancialUseCase(
            provider_repo=provider_repository,
            provider_registry=provider_registry,
            fact_repo=financial_repository,
            raw_audit_repo=raw_audit_repository,
            publication_publisher=None,
        ),
        financial_availability=FinancialAvailabilityBackfillUseCase(
            repository=financial_repository,
            transaction=transaction.atomic,
        ),
        completed_session_prices=CompletedSessionPriceBarUseCase(
            quote_repository=quote_repository,
            price_repository=price_repository,
            transaction=transaction.atomic,
        ),
        publications=make_core_current_publication_rebuild_use_case(
            created_by=created_by,
        ),
    )


def get_rollback_canonical_publication_use_case(
    *, environment: str = "production"
) -> RollbackCanonicalPublicationUseCase:
    """Compose publication rollback, evidence, and required audit atomically."""

    from core.integration.data_center_audit import (
        get_data_publication_rollback_audit_writer,
    )

    repository = get_canonical_publication_repository()
    audit_writer = get_data_publication_rollback_audit_writer(
        environment=environment,
        using="default",
    )
    return RollbackCanonicalPublicationUseCase(
        repository,
        audit_writer=audit_writer,
        unit_of_work=DjangoDataCenterSyncUnitOfWork(
            (repository,),
            audit_writer,
            using="default",
        ),
        clock=DjangoDataCenterSyncClock(),
    )


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


def get_alpha_price_coverage_sync_service() -> object:
    """Compose Alpha price-coverage maintenance behind the Data Center boundary."""

    from apps.data_center.infrastructure.alpha_price_coverage_sync import (
        AlphaPriceCoverageSyncService,
    )

    return AlphaPriceCoverageSyncService()


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


@dataclass(frozen=True, slots=True)
class RepairRunAuditDependencies:
    """Canonical identity, transaction, writer, and clock for one repair run."""

    identity_issuer: SyncExecutionIdentityIssuer
    identity_unit_of_work: DataCenterSyncUnitOfWork
    audit_writer: DataRepairAuditWriter
    clock: DataCenterSyncClock


def make_repair_run_audit_dependencies(
    *, environment: str = "production"
) -> RepairRunAuditDependencies:
    """Compose the durable parent identity and scoped completion writer."""

    from core.integration.data_center_audit import get_data_repair_audit_writer

    identity_repository = SyncExecutionIdentityRepository()
    return RepairRunAuditDependencies(
        identity_issuer=DjangoSyncExecutionIdentityIssuer(
            identity_repository,
            using="default",
        ),
        identity_unit_of_work=DjangoRepairRunIdentityUnitOfWork(
            identity_repository,
            using="default",
        ),
        audit_writer=get_data_repair_audit_writer(
            environment=environment,
            using="default",
        ),
        clock=DjangoDataCenterSyncClock(),
    )


def make_system_audited_sync_macro_use_case(
    *,
    provider_repository: ProviderConfigRepositoryProtocol | None = None,
    provider_registry: ProviderRegistryProtocol | None = None,
    environment: str = "production",
) -> SyncMacroUseCase:
    """Compose the canonical same-UOW macro sync writer."""

    # Import at the cross-App composition boundary so importing data-center query
    # services does not eagerly initialize the audit repository graph.
    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    provider_repo = provider_repository or ProviderConfigRepository()
    registry = provider_registry or build_provider_registry_for_repo(provider_repo)
    macro_repo = MacroFactRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    (
        fetch_audit_writer,
        publication_audit_writer,
        validation_audit_writer,
        failover_audit_writer,
        _decision_read_audit_writer,
        provider_health_audit_writer,
        _freshness_audit_writer,
        quality_audit_writer,
    ) = get_data_reliability_audit_writers(environment=environment, using="default")
    identity_issuer = DjangoSyncExecutionIdentityIssuer(identity_repo, using="default")
    sync_clock = DjangoDataCenterSyncClock()
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=publication_repo,
        quality_writer=quality_audit_writer,
        clock=sync_clock,
    )
    sync_uow = DjangoDataCenterSyncUnitOfWork(
        (
            cast(DataCenterSyncUnitOfWorkParticipant, provider_repo),
            macro_repo,
            raw_audit_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        fetch_audit_writer,
        additional_audit_writers=(
            publication_audit_writer,
            validation_audit_writer,
            failover_audit_writer,
            provider_health_audit_writer,
            quality_audit_writer,
        ),
        using="default",
    )
    return SyncMacroUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=macro_repo,
        catalog_repo=IndicatorCatalogRepository(),
        unit_rule_repo=IndicatorUnitRuleRepository(),
        raw_audit_repo=raw_audit_repo,
        publication_publisher=PublishMacroBatchUseCase(
            fact_repository=macro_repo,
            publication_repository=publication_repo,
            policy_repository=policy_repo,
        ),
        sync_identity_issuer=identity_issuer,
        sync_unit_of_work=sync_uow,
        data_fetch_audit_writer=fetch_audit_writer,
        data_publication_audit_writer=publication_audit_writer,
        publication_quality_recorder=quality_recorder,
        data_validation_audit_writer=validation_audit_writer,
        data_failover_audit_writer=failover_audit_writer,
        clock=sync_clock,
        data_provider_health_audit_writer=provider_health_audit_writer,
    )


def make_data_chain_replay_use_case() -> ReplayDataChainUseCase:
    """Compose the exact system-audit and professional-evidence replay path."""

    from core.integration.data_center_audit import (
        ListCorrelatedSystemAuditEventsUseCase,
        get_system_audit_event_repository,
    )

    return ReplayDataChainUseCase(
        correlation_query=ListCorrelatedSystemAuditEventsUseCase(
            get_system_audit_event_repository()
        ),
        raw_audit_reader=RawAuditRepository(),
        publication_reader=CanonicalPublicationRepository(),
        fact_evidence_reader=DjangoReplayFactEvidenceReader(),
    )


def make_repair_run_replay_use_case() -> ReplayRepairRunUseCase:
    """Compose parent repair replay with exact identity and child-chain readers."""

    from core.integration.data_center_audit import (
        ListCorrelatedSystemAuditEventsUseCase,
        get_system_audit_event_repository,
    )

    return ReplayRepairRunUseCase(
        correlation_query=ListCorrelatedSystemAuditEventsUseCase(
            get_system_audit_event_repository()
        ),
        identity_reader=SyncExecutionIdentityRepository(),
        publication_replay=make_data_chain_replay_use_case(),
    )


def make_publication_decision_read_recorder(
    *, environment: str = "production"
) -> RecordPublicationDecisionReadUseCase:
    """Compose the canonical publication-bound decision-read recorder."""

    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    audit_writers = get_data_reliability_audit_writers(
        environment=environment,
        using="default",
    )
    return RecordPublicationDecisionReadUseCase(
        writer=audit_writers[4],
        clock=DjangoDataCenterSyncClock(),
        freshness_writer=audit_writers[6],
    )


def make_system_audited_sync_price_use_case(
    *,
    provider_repository: ProviderConfigRepositoryProtocol | None = None,
    provider_registry: ProviderRegistryProtocol | None = None,
    environment: str = "production",
    publish_current: bool = True,
) -> SyncPriceUseCase:
    """Compose the canonical same-UOW historical-price sync writer."""

    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    provider_repo = provider_repository or ProviderConfigRepository()
    registry = provider_registry or build_provider_registry_for_repo(provider_repo)
    price_repo = PriceBarRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    (
        fetch_audit_writer,
        publication_audit_writer,
        _validation_audit_writer,
        _failover_audit_writer,
        _decision_read_audit_writer,
        provider_health_audit_writer,
        _freshness_audit_writer,
        quality_audit_writer,
    ) = get_data_reliability_audit_writers(environment=environment, using="default")
    identity_issuer = DjangoSyncExecutionIdentityIssuer(identity_repo, using="default")
    sync_clock = DjangoDataCenterSyncClock()
    quality_recorder = (
        RecordPublicationQualityUseCase(
            publication_reader=publication_repo,
            quality_writer=quality_audit_writer,
            clock=sync_clock,
        )
        if publish_current
        else None
    )
    sync_uow = DjangoDataCenterSyncUnitOfWork(
        (
            cast(DataCenterSyncUnitOfWorkParticipant, provider_repo),
            price_repo,
            raw_audit_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        fetch_audit_writer,
        additional_audit_writers=(
            publication_audit_writer,
            provider_health_audit_writer,
            quality_audit_writer,
        ),
        using="default",
    )
    return SyncPriceUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=price_repo,
        raw_audit_repo=raw_audit_repo,
        publication_publisher=(
            PublishPriceBarBatchUseCase(
                fact_repository=price_repo,
                publication_repository=publication_repo,
                policy_repository=policy_repo,
            )
            if publish_current
            else None
        ),
        sync_identity_issuer=identity_issuer,
        sync_unit_of_work=sync_uow,
        data_fetch_audit_writer=fetch_audit_writer,
        data_publication_audit_writer=publication_audit_writer,
        publication_quality_recorder=quality_recorder,
        clock=sync_clock,
        data_provider_health_audit_writer=provider_health_audit_writer,
    )


def make_system_audited_sync_quote_use_case(
    *,
    provider_repository: ProviderConfigRepositoryProtocol | None = None,
    provider_registry: ProviderRegistryProtocol | None = None,
    environment: str = "production",
    publish_current: bool = True,
) -> SyncQuoteUseCase:
    """Compose the canonical same-UOW realtime-quote sync writer."""

    from core.integration.data_center_audit import (
        get_data_reliability_audit_writers,
    )

    provider_repo = provider_repository or ProviderConfigRepository()
    registry = provider_registry or build_provider_registry_for_repo(provider_repo)
    quote_repo = QuoteSnapshotRepository()
    raw_audit_repo = RawAuditRepository()
    publication_repo = CanonicalPublicationRepository()
    policy_repo = PublicationPolicyRepository()
    identity_repo = SyncExecutionIdentityRepository()
    (
        fetch_audit_writer,
        publication_audit_writer,
        _validation_audit_writer,
        _failover_audit_writer,
        _decision_read_audit_writer,
        provider_health_audit_writer,
        _freshness_audit_writer,
        quality_audit_writer,
    ) = get_data_reliability_audit_writers(environment=environment, using="default")
    identity_issuer = DjangoSyncExecutionIdentityIssuer(identity_repo, using="default")
    sync_clock = DjangoDataCenterSyncClock()
    quality_recorder = (
        RecordPublicationQualityUseCase(
            publication_reader=publication_repo,
            quality_writer=quality_audit_writer,
            clock=sync_clock,
        )
        if publish_current
        else None
    )
    sync_uow = DjangoDataCenterSyncUnitOfWork(
        (
            cast(DataCenterSyncUnitOfWorkParticipant, provider_repo),
            quote_repo,
            raw_audit_repo,
            publication_repo,
            policy_repo,
            identity_repo,
        ),
        fetch_audit_writer,
        additional_audit_writers=(
            publication_audit_writer,
            provider_health_audit_writer,
            quality_audit_writer,
        ),
        using="default",
    )
    return SyncQuoteUseCase(
        provider_repo=provider_repo,
        provider_registry=registry,
        fact_repo=quote_repo,
        raw_audit_repo=raw_audit_repo,
        publication_publisher=(
            PublishQuoteSnapshotBatchUseCase(
                fact_repository=quote_repo,
                publication_repository=publication_repo,
                policy_repository=policy_repo,
            )
            if publish_current
            else None
        ),
        sync_identity_issuer=identity_issuer,
        sync_unit_of_work=sync_uow,
        data_fetch_audit_writer=fetch_audit_writer,
        data_publication_audit_writer=publication_audit_writer,
        publication_quality_recorder=quality_recorder,
        clock=sync_clock,
        data_provider_health_audit_writer=provider_health_audit_writer,
    )


def make_macro_failover_policy_provider(
    *, environment: str = "production"
) -> MacroFailoverPolicyProvider:
    """Compose the runtime-backed macro failover policy provider."""

    return ConfigCenterMacroFailoverPolicyProvider(environment=environment)


def build_tushare_client(*, token: str | None = None, http_url: str | None = None) -> object:
    """Build the Data Center-owned Tushare transport behind the composition root."""

    from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client

    return create_tushare_pro_client(token=token, http_url=http_url)


def refresh_provider_registry() -> ProviderRegistry:
    """Refresh and return the process-wide canonical provider registry."""

    from apps.data_center.provider_runtime import refresh_registry

    return refresh_registry()


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
