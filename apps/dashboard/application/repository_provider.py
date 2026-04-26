"""Repository providers for dashboard application services."""

from apps.account.application.repository_provider import (
    get_account_position_repository,
    get_account_repository,
    get_portfolio_repository,
)
from apps.dashboard.infrastructure.providers import (
    DashboardAIInsightClient,
    DashboardOverviewRepository,
)
from apps.regime.application.repository_provider import get_regime_repository
from apps.signal.application.repository_provider import get_signal_repository


def get_position_repository():
    """Return the default position repository."""
    return get_account_position_repository()


def get_dashboard_overview_repository() -> DashboardOverviewRepository:
    """Return the dashboard overview read model repository."""
    return DashboardOverviewRepository()


def get_dashboard_ai_insight_client() -> DashboardAIInsightClient:
    """Return the dashboard AI insight client."""
    from apps.dashboard.infrastructure.providers import get_dashboard_ai_insight_client as factory

    return factory()
