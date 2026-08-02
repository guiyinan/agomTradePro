"""Compatibility exports for Data Center ORM repositories.

Repository implementations live in focused owner modules grouped by
persistence responsibility (provider state, market thermometer, catalogs,
macro facts, market data, fundamental facts, and market breadth). Keep this
module as the stable import and patch surface for callers while preventing
the former monolith from regrowing.
"""

from apps.data_center.infrastructure._repository_helpers import (
    _build_asset_code_candidates,
)
from apps.data_center.infrastructure.catalog_repositories import (
    AssetRepository,
    IndicatorCatalogRepository,
    IndicatorUnitRuleRepository,
    PublisherCatalogRepository,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    DataOwnerRegistryRepository,
    DatasetContractRepository,
    ProviderBindingRepository,
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.fundamental_fact_repositories import (
    FinancialFactRepository,
    FundNavRepository,
    ValuationFactRepository,
)
from apps.data_center.infrastructure.macro_fact_repositories import (
    MacroFactRepository,
    MacroGovernanceRepository,
)
from apps.data_center.infrastructure.market_breadth_repositories import (
    CapitalFlowRepository,
    NewsRepository,
    SectorMembershipRepository,
)
from apps.data_center.infrastructure.market_data_repositories import (
    PriceBarRepository,
    QuoteSnapshotRepository,
)
from apps.data_center.infrastructure.market_thermometer_repositories import (
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
)
from apps.data_center.infrastructure.provider_state_repositories import (
    DataProviderSettingsRepository,
    ProductionCoverageUniverseConfigRepository,
    ProviderConfigRepository,
    RawAuditRepository,
)
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    ReconciliationEvidenceRepository,
)

__all__ = [
    "AssetRepository",
    "DataOwnerRegistryRepository",
    "CapitalFlowRepository",
    "DataProviderSettingsRepository",
    "DatasetContractRepository",
    "FinancialFactRepository",
    "FundNavRepository",
    "IndicatorCatalogRepository",
    "IndicatorUnitRuleRepository",
    "MacroFactRepository",
    "MacroGovernanceRepository",
    "MarketThermometerConfigRepository",
    "MarketThermometerSnapshotRepository",
    "MarketThermometerUserOverrideRepository",
    "NewsRepository",
    "PriceBarRepository",
    "ProductionCoverageUniverseConfigRepository",
    "ProviderConfigRepository",
    "ProviderBindingRepository",
    "PublisherCatalogRepository",
    "PublicationPolicyRepository",
    "QuoteSnapshotRepository",
    "RawAuditRepository",
    "ReconciliationEvidenceRepository",
    "SectorMembershipRepository",
    "ValuationFactRepository",
    "_build_asset_code_candidates",
]
