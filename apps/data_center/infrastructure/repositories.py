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
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.fund_nav_repository import FundNavRepository
from apps.data_center.infrastructure.macro_fact_repositories import MacroGovernanceRepository
from apps.data_center.infrastructure.macro_fact_storage_repository import MacroFactRepository
from apps.data_center.infrastructure.market_breadth_repositories import (
    CapitalFlowRepository,
    SectorMembershipRepository,
)
from apps.data_center.infrastructure.market_thermometer_repositories import (
    MarketThermometerConfigRepository,
    MarketThermometerSnapshotRepository,
    MarketThermometerUserOverrideRepository,
)
from apps.data_center.infrastructure.news_repository import NewsRepository
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.provider_state_repositories import (
    ProductionCoverageUniverseConfigRepository,
    ProviderConfigRepository,
    RawAuditRepository,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.reconciliation_evidence_repositories import (
    ReconciliationEvidenceRepository,
)
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

__all__ = [
    "AssetRepository",
    "DataOwnerRegistryRepository",
    "CapitalFlowRepository",
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
