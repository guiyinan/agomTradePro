"""Repository providers for dashboard application services."""

from apps.account.infrastructure.providers import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.dashboard.infrastructure.providers import (
    DashboardAIInsightClient,
    DashboardOverviewRepository,
)
from apps.regime.infrastructure.providers import DjangoRegimeRepository
from apps.signal.infrastructure.providers import DjangoSignalRepository


def get_account_repository() -> AccountRepository:
    """Return the default account repository."""
    return AccountRepository()


def get_portfolio_repository() -> PortfolioRepository:
    """Return the default portfolio repository."""
    return PortfolioRepository()


def get_position_repository() -> PositionRepository:
    """Return the default position repository."""
    return PositionRepository()


def get_regime_repository() -> DjangoRegimeRepository:
    """Return the default regime repository."""
    return DjangoRegimeRepository()


def get_signal_repository() -> DjangoSignalRepository:
    """Return the default signal repository."""
    return DjangoSignalRepository()


def get_dashboard_overview_repository() -> DashboardOverviewRepository:
    """Return the dashboard overview read model repository."""
    return DashboardOverviewRepository()


def get_dashboard_ai_insight_client() -> DashboardAIInsightClient:
    """Return the dashboard AI insight client."""
    from apps.dashboard.infrastructure.providers import get_dashboard_ai_insight_client as factory

    return factory()
