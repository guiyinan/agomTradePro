"""Repository provider helpers for equity application consumers."""

from __future__ import annotations

from apps.equity.infrastructure.adapters import (
    RegimeRepositoryAdapter,
    StockPoolRepositoryAdapter,
    TushareStockAdapter,
)
from apps.equity.infrastructure.providers import (
    DjangoEquityAssetRepository,
    DjangoStockRepository,
    DjangoValuationDataQualityRepository,
    DjangoValuationRepairRepository,
    EquityBootstrapConfigRepository,
    ValuationRepairConfigRepository,
)
from apps.regime.application.repository_provider import get_regime_repository


def get_equity_stock_repository() -> DjangoStockRepository:
    """Return the default equity stock repository."""

    return DjangoStockRepository()


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
