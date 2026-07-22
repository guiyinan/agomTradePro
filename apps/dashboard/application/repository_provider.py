"""Repository providers for dashboard application services."""

from apps.account.application.repository_provider import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
)
from apps.account.application.repository_provider import (
    get_account_position_repository as _get_account_position_repository,
)
from apps.account.application.repository_provider import (
    get_account_repository as _get_account_repository,
)
from apps.account.application.repository_provider import (
    get_portfolio_repository as _get_portfolio_repository,
)
from apps.dashboard.application.integration_gateways import (
    build_dashboard_application_gateway,
)
from apps.dashboard.infrastructure.providers import (
    AlphaRecommendationHistoryRepository as AlphaRecommendationHistoryRepository,
)
from apps.dashboard.infrastructure.providers import (
    AutoAdvisorReportRepository as AutoAdvisorReportRepository,
)
from apps.dashboard.infrastructure.providers import (
    DashboardAIInsightClient as DashboardAIInsightClient,
)
from apps.dashboard.infrastructure.providers import (
    DashboardAlphaContextRepository as DashboardAlphaContextRepository,
)
from apps.dashboard.infrastructure.providers import (
    DashboardOverviewRepository as DashboardOverviewRepository,
)
from apps.dashboard.infrastructure.providers import (
    DashboardQueryRepository as DashboardQueryRepository,
)
from apps.regime.application.repository_provider import (
    DjangoRegimeRepository,
)
from apps.regime.application.repository_provider import (
    get_regime_repository as _get_regime_repository,
)
from apps.signal.application.repository_provider import (
    DjangoSignalRepository,
)
from apps.signal.application.repository_provider import (
    get_signal_repository as _get_signal_repository,
)


def get_account_repository() -> AccountRepository:
    """Return the default account repository."""

    return _get_account_repository()


def get_portfolio_repository() -> PortfolioRepository:
    """Return the default portfolio repository."""

    return _get_portfolio_repository()


def get_position_repository() -> PositionRepository:
    """Return the default position repository."""

    return _get_account_position_repository()


def get_regime_repository() -> DjangoRegimeRepository:
    """Return the default Regime repository."""

    return _get_regime_repository()


def get_signal_repository() -> DjangoSignalRepository:
    """Return the default signal repository."""

    return _get_signal_repository()


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


def get_auto_advisor_report_repository() -> AutoAdvisorReportRepository:
    """Return the auto-advisor report persistence repository."""

    return AutoAdvisorReportRepository()


def get_dashboard_ai_insight_client() -> DashboardAIInsightClient:
    """Return the dashboard AI insight client."""
    from apps.dashboard.infrastructure.providers import get_dashboard_ai_insight_client as factory

    return factory()
