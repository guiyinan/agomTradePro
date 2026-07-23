"""Concrete dependency composition for Simulated Trading workflows."""

from apps.simulated_trading.application.performance_use_cases import (
    AccountRepositoryProtocol,
    BenchmarkComponentRepositoryProtocol,
    CapitalFlowRepositoryProtocol,
    DailyNetValueRepositoryProtocol,
    MarketDataRepositoryProtocol,
    ObserverGrantRepositoryProtocol,
    TradeHistoryRepositoryProtocol,
    UnifiedCashFlowRepositoryProtocol,
    ValuationSnapshotRepositoryProtocol,
)
from apps.simulated_trading.infrastructure.performance_repositories import (
    DjangoBenchmarkComponentRepository,
    DjangoCapitalFlowRepository,
    DjangoMarketDataRepository,
    DjangoObserverGrantRepository,
    DjangoPerformanceAccountRepository,
    DjangoPerformanceDailyNetValueRepository,
    DjangoTradeHistoryRepository,
    DjangoUnifiedCashFlowRepository,
    DjangoValuationSnapshotRepository,
)


def build_performance_account_repository() -> AccountRepositoryProtocol:
    """Build the account read repository used by performance workflows."""
    return DjangoPerformanceAccountRepository()


def build_observer_grant_repository() -> ObserverGrantRepositoryProtocol:
    """Build the observer authorization repository."""
    return DjangoObserverGrantRepository()


def build_daily_net_value_repository() -> DailyNetValueRepositoryProtocol:
    """Build the daily net-value repository."""
    return DjangoPerformanceDailyNetValueRepository()


def build_unified_cash_flow_repository() -> UnifiedCashFlowRepositoryProtocol:
    """Build the unified cash-flow repository."""
    return DjangoUnifiedCashFlowRepository()


def build_benchmark_component_repository() -> BenchmarkComponentRepositoryProtocol:
    """Build the benchmark component repository."""
    return DjangoBenchmarkComponentRepository()


def build_market_data_repository() -> MarketDataRepositoryProtocol:
    """Build the market-data repository."""
    return DjangoMarketDataRepository()


def build_trade_history_repository() -> TradeHistoryRepositoryProtocol:
    """Build the closed-trade history repository."""
    return DjangoTradeHistoryRepository()


def build_valuation_snapshot_repository() -> ValuationSnapshotRepositoryProtocol:
    """Build the valuation snapshot repository."""
    return DjangoValuationSnapshotRepository()


def build_capital_flow_repository() -> CapitalFlowRepositoryProtocol:
    """Build the legacy capital-flow adapter used by backfill."""
    return DjangoCapitalFlowRepository()
