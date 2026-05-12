"""Repository providers for dashboard application services."""

from apps.account.application.repository_provider import (
    get_account_position_repository,
    get_account_repository,  # noqa: F401
    get_portfolio_repository,  # noqa: F401
)
from apps.dashboard.application.integration_gateways import (
    build_dashboard_application_gateway,
)
from apps.dashboard.infrastructure.providers import (
    AlphaRecommendationHistoryRepository,
    DashboardAIInsightClient,
    DashboardAlphaContextRepository,
    DashboardOverviewRepository,
    DashboardQueryRepository,
)
from apps.regime.application.repository_provider import get_regime_repository  # noqa: F401
from apps.signal.application.repository_provider import get_signal_repository  # noqa: F401


def get_position_repository():
    """Return the default position repository."""
    return get_account_position_repository()


def get_dashboard_overview_repository() -> DashboardOverviewRepository:
    """Return the dashboard overview read model repository."""
    return DashboardOverviewRepository(build_dashboard_application_gateway())


def get_dashboard_query_repository() -> DashboardQueryRepository:
    """Return the dashboard query repository."""

    return DashboardQueryRepository(build_dashboard_application_gateway())


def get_dashboard_alpha_context_repository() -> DashboardAlphaContextRepository:
    """Return the dashboard Alpha context repository."""

    return DashboardAlphaContextRepository(build_dashboard_application_gateway())


def get_alpha_recommendation_history_repository() -> AlphaRecommendationHistoryRepository:
    """Return the Alpha recommendation history repository."""

    return AlphaRecommendationHistoryRepository()


def get_dashboard_ai_insight_client() -> DashboardAIInsightClient:
    """Return the dashboard AI insight client."""
    from apps.dashboard.infrastructure.providers import get_dashboard_ai_insight_client as factory

    return factory()
