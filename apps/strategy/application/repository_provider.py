"""Providers for strategy application/interface services."""

from typing import cast

from apps.strategy.application.interface_contracts import (
    StrategyExecutionRunnerProtocol,
    StrategyInterfaceRepositoryProtocol,
    StrategyPortfolioProviderProtocol,
)
from apps.strategy.domain.allocation_policy_protocols import (
    AllocationPolicyRepositoryProtocol,
)
from apps.strategy.domain.protocols import (
    AssetPoolProviderProtocol,
    PortfolioDataProviderProtocol,
    SignalProviderProtocol,
)
from apps.strategy.infrastructure.allocation_policy_repository import (
    DjangoAllocationPolicyRepository,
)
from apps.strategy.infrastructure.providers import (
    DjangoAssetPoolProvider,
    DjangoMacroDataProvider,
    DjangoPortfolioDataProvider,
    DjangoRegimeProvider,
    DjangoSignalProvider,
    DjangoStrategyExecutionLogRepository,
    DjangoStrategyGatewayRepository,
    DjangoStrategyRepository,
    StrategyInterfaceRepository,
)


def get_strategy_interface_repository() -> StrategyInterfaceRepositoryProtocol:
    """Return the strategy interface repository."""

    return cast(StrategyInterfaceRepositoryProtocol, StrategyInterfaceRepository())


def get_allocation_policy_repository() -> AllocationPolicyRepositoryProtocol:
    """Return the Strategy-owned allocation-policy repository adapter."""

    return cast(AllocationPolicyRepositoryProtocol, DjangoAllocationPolicyRepository())


def get_strategy_gateway_repository() -> DjangoStrategyGatewayRepository:
    """Return the strategy gateway query repository."""

    return DjangoStrategyGatewayRepository()


def build_prompt_strategy_providers() -> tuple[
    PortfolioDataProviderProtocol,
    SignalProviderProtocol,
    AssetPoolProviderProtocol,
]:
    """Return strategy-owned providers used by prompt agent runtime."""

    return (
        DjangoPortfolioDataProvider(),
        DjangoSignalProvider(),
        DjangoAssetPoolProvider(),
    )


def build_strategy_executor() -> StrategyExecutionRunnerProtocol:
    """Build a StrategyExecutor wired with infrastructure dependencies."""

    from apps.strategy.application.strategy_executor import StrategyExecutor

    return cast(
        StrategyExecutionRunnerProtocol,
        StrategyExecutor(
            strategy_repository=DjangoStrategyRepository(),
            execution_log_repository=DjangoStrategyExecutionLogRepository(),
            macro_provider=DjangoMacroDataProvider(),
            regime_provider=DjangoRegimeProvider(),
            asset_pool_provider=DjangoAssetPoolProvider(),
            signal_provider=DjangoSignalProvider(),
            portfolio_provider=DjangoPortfolioDataProvider(),
            script_security_mode="relaxed",
        ),
    )


def build_strategy_portfolio_provider() -> StrategyPortfolioProviderProtocol:
    """Return the strategy-owned adapter for portfolio reads."""

    return cast(StrategyPortfolioProviderProtocol, DjangoPortfolioDataProvider())
