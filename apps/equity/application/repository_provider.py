"""Repository provider helpers for equity application consumers."""

from __future__ import annotations

from apps.equity.infrastructure.adapters import (
    MarketDataRepositoryAdapter,
    RegimeRepositoryAdapter,
    StockPoolRepositoryAdapter,
    TushareStockAdapter,
)
from apps.equity.infrastructure.config_loader import get_stock_screening_rule  # noqa: F401
from apps.equity.infrastructure.providers import (
    DjangoEquityAssetRepository,
    DjangoStockRepository,
    DjangoValuationDataQualityRepository,
    DjangoValuationRepairRepository,
    EquityBootstrapConfigRepository,
    ScoringWeightConfigRepository,
    ValuationRepairConfigRepository,
    build_quality_snapshot,  # noqa: F401
)
from apps.equity.infrastructure.valuation_source_gateways import (
    AKShareValuationGateway,
    TushareValuationGateway,
)
from apps.regime.application.repository_provider import get_regime_repository


def get_equity_stock_repository() -> DjangoStockRepository:
    """Return the default equity stock repository."""

    return DjangoStockRepository()


def resolve_equity_names(codes: list[str]) -> dict[str, str]:
    """Resolve equity display names through the equity stock repository."""

    return get_equity_stock_repository().resolve_stock_names(codes)


def get_equity_valuation_repair_repository() -> DjangoValuationRepairRepository:
    """Return the default equity valuation repair repository."""

    return DjangoValuationRepairRepository()


def get_equity_valuation_data_quality_repository() -> DjangoValuationDataQualityRepository:
    """Return the default equity valuation data quality repository."""

    return DjangoValuationDataQualityRepository()


def get_equity_regime_repository() -> RegimeRepositoryAdapter:
    """Return the default regime adapter used by equity workflows."""

    return RegimeRepositoryAdapter()


def get_equity_regime_history_repository():
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


def get_equity_valuation_repair_config_repository() -> ValuationRepairConfigRepository:
    """Return the valuation repair config repository."""

    return ValuationRepairConfigRepository()


def build_akshare_valuation_gateway() -> AKShareValuationGateway:
    """Build the AKShare valuation gateway."""

    return AKShareValuationGateway()


def build_tushare_valuation_gateway(
    *, token: str, http_url: str | None = None
) -> TushareValuationGateway:
    """Build the Tushare valuation gateway."""

    return TushareValuationGateway(token=token, http_url=http_url)
