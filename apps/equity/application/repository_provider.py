"""Repository provider helpers for equity application consumers."""

from __future__ import annotations

# isort: off
from typing import TYPE_CHECKING, TypeAlias

from apps.equity.domain.rules import StockScreeningRule
from apps.equity.infrastructure.adapters import (
    MarketDataRepositoryAdapter,
)
from apps.equity.infrastructure.adapters import RegimeRepositoryAdapter as _RegimeRepositoryAdapter
from apps.equity.infrastructure.adapters import (
    StockPoolRepositoryAdapter as _StockPoolRepositoryAdapter,
)
from apps.equity.infrastructure.adapters import TushareStockAdapter as _TushareStockAdapter
from apps.equity.infrastructure.asset_master_queries import EquityAssetMasterQueryRepository
from apps.equity.infrastructure.config_loader import (
    get_stock_screening_rule as _load_stock_screening_rule,
)
from apps.equity.infrastructure.providers import (
    DjangoEquityAssetRepository,
    DjangoValuationDataQualityRepository,
    DjangoValuationRepairRepository,
    EquityBootstrapConfigRepository,
    ScoringWeightConfigRepository,
    ValuationRepairConfigRepository,
)
from apps.equity.infrastructure.providers import DjangoStockRepository as _DjangoStockRepository
from apps.equity.infrastructure.providers import build_quality_snapshot as build_quality_snapshot
from apps.equity.infrastructure.valuation_source_gateways import (
    AKShareValuationGateway,
    ConfiguredValuationGateway,
)
from apps.equity.infrastructure.valuation_source_gateways import (
    TushareValuationGateway as TushareValuationGateway,
)
from apps.regime.application.repository_provider import (
    DjangoRegimeRepository,
    get_regime_repository,
)

# isort: on

if TYPE_CHECKING:
    from apps.equity.infrastructure.financial_source_gateway import (
        TushareFinancialGateway as TushareFinancialGateway,
    )

DjangoStockRepository: TypeAlias = _DjangoStockRepository
RegimeRepositoryAdapter: TypeAlias = _RegimeRepositoryAdapter
StockPoolRepositoryAdapter: TypeAlias = _StockPoolRepositoryAdapter
TushareStockAdapter: TypeAlias = _TushareStockAdapter


def get_equity_stock_repository() -> DjangoStockRepository:
    """Return the default equity stock repository."""

    return DjangoStockRepository()


def get_equity_asset_master_query_repository() -> EquityAssetMasterQueryRepository:
    """Return the equity asset-master query repository."""

    return EquityAssetMasterQueryRepository()


def resolve_equity_names(codes: list[str]) -> dict[str, str]:
    """Resolve equity display names through the equity stock repository."""

    return dict(get_equity_stock_repository().resolve_stock_names(codes))


def get_equity_valuation_repair_repository() -> DjangoValuationRepairRepository:
    """Return the default equity valuation repair repository."""

    return DjangoValuationRepairRepository()


def get_equity_valuation_data_quality_repository() -> DjangoValuationDataQualityRepository:
    """Return the default equity valuation data quality repository."""

    return DjangoValuationDataQualityRepository()


def get_equity_regime_repository() -> RegimeRepositoryAdapter:
    """Return the default regime adapter used by equity workflows."""

    return RegimeRepositoryAdapter()


def get_equity_regime_history_repository() -> DjangoRegimeRepository:
    """Return the concrete regime history repository for correlation analysis."""

    return get_regime_repository()


def get_equity_stock_pool_repository() -> StockPoolRepositoryAdapter:
    """Return the default stock pool repository."""

    return StockPoolRepositoryAdapter()


def get_equity_market_data_repository() -> MarketDataRepositoryAdapter:
    """Return the default market data adapter used by equity workflows."""

    return MarketDataRepositoryAdapter()


def get_tushare_stock_adapter() -> TushareStockAdapter:
    """Return the default Tushare stock adapter."""

    return TushareStockAdapter()


def build_tushare_financial_gateway(
    *, token: str, http_url: str | None = None
) -> TushareFinancialGateway:
    """Build the Tushare financial gateway."""

    from apps.equity.infrastructure.financial_source_gateway import TushareFinancialGateway

    return TushareFinancialGateway(token=token, http_url=http_url)


def get_equity_asset_repository() -> DjangoEquityAssetRepository:
    """Return the equity asset repository used by multidimensional scoring."""

    return DjangoEquityAssetRepository()


def get_equity_valuation_repair_config_repository() -> ValuationRepairConfigRepository:
    """Return the valuation repair config repository."""

    return ValuationRepairConfigRepository()


def get_equity_bootstrap_config_repository() -> EquityBootstrapConfigRepository:
    """Return the bootstrap config repository used by init commands."""

    return EquityBootstrapConfigRepository()


def get_equity_scoring_weight_config_repository() -> ScoringWeightConfigRepository:
    """Return the scoring weight config repository."""

    return ScoringWeightConfigRepository()


def get_stock_screening_rule(regime: str) -> StockScreeningRule | None:
    """Return the configured screening rule through the application provider boundary."""

    return _load_stock_screening_rule(regime)


def build_akshare_valuation_gateway() -> AKShareValuationGateway:
    """Build the AKShare valuation gateway."""

    return AKShareValuationGateway()


def build_equity_valuation_source_gateway(*, provider_name: str) -> ConfiguredValuationGateway:
    """Build a valuation fact reader for one configured provider."""

    return ConfiguredValuationGateway(provider_name=provider_name)


def build_tushare_valuation_gateway(
    *, token: str, http_url: str | None = None
) -> TushareValuationGateway:
    """Build the Tushare valuation gateway."""

    return TushareValuationGateway(token=token, http_url=http_url)
