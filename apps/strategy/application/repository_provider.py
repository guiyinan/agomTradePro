"""Providers for strategy application/interface services."""

from apps.strategy.infrastructure.providers import (
    DjangoAssetPoolProvider,
    DjangoStrategyExecutionLogRepository,
    DjangoStrategyGatewayRepository,
    DjangoMacroDataProvider,
    DjangoPortfolioDataProvider,
    DjangoRegimeProvider,
    DjangoSignalProvider,
    DjangoStrategyRepository,
    StrategyInterfaceRepository,
)


def get_strategy_interface_repository() -> StrategyInterfaceRepository:
    """Return the strategy interface repository."""

    return StrategyInterfaceRepository()


def get_strategy_gateway_repository() -> DjangoStrategyGatewayRepository:
    """Return the strategy gateway query repository."""

    return DjangoStrategyGatewayRepository()


def build_strategy_executor():
    """Build a StrategyExecutor wired with infrastructure dependencies."""

    from apps.strategy.application.strategy_executor import StrategyExecutor

    return StrategyExecutor(
        strategy_repository=DjangoStrategyRepository(),
        execution_log_repository=DjangoStrategyExecutionLogRepository(),
        macro_provider=DjangoMacroDataProvider(),
        regime_provider=DjangoRegimeProvider(),
        asset_pool_provider=DjangoAssetPoolProvider(),
        signal_provider=DjangoSignalProvider(),
        portfolio_provider=DjangoPortfolioDataProvider(),
        script_security_mode="relaxed",
    )
