"""Application-facing helpers for dashboard interface views."""

from __future__ import annotations

from apps.dashboard.application.repository_provider import (
    get_portfolio_repository,
    get_dashboard_overview_repository,
)
from apps.dashboard.application.use_cases import GetDashboardDataUseCase


def build_dashboard_data(user_id: int):
    """Build dashboard DTO for API and page views."""
    use_case = GetDashboardDataUseCase()
    return use_case.execute(user_id)


def build_performance_chart_data(
    user_id: int,
    account_id: int | None = None,
) -> list[dict]:
    """Build performance chart data for dashboard HTMX/API views."""
    use_case = GetDashboardDataUseCase()
    return use_case._generate_performance_chart_data(
        user_id=user_id,
        account_id=account_id,
    )


def get_portfolio_options(user_id: int) -> list[dict]:
    """Load user portfolio options for dashboard selectors."""
    return get_portfolio_repository().get_user_portfolios(user_id)


def load_simulated_positions_fallback(
    user_id: int,
    account_id: int | None = None,
) -> list[dict]:
    """Load simulated-account holdings for dashboard fallbacks."""
    return get_dashboard_overview_repository().get_simulated_positions_for_dashboard(
        user_id=user_id,
        account_id=account_id,
    )


def get_dashboard_accounts(user) -> list[dict]:
    """Load investment accounts for dashboard account cards."""
    user_id = getattr(user, "id", None)
    if user_id in (None, ""):
        return []
    return get_dashboard_overview_repository().get_dashboard_accounts(int(user_id))


def ensure_dashboard_positions(data, user_id: int):
    """Backfill positions for rendering when the portfolio snapshot is stale."""
    if data.positions or data.invested_value <= 0:
        return data

    fallback_positions = load_simulated_positions_fallback(user_id)
    if not fallback_positions:
        return data

    data.positions = fallback_positions
    data.position_count = len(fallback_positions)
    return data
