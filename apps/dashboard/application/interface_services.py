"""Application-facing helpers for dashboard interface views."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from apps.dashboard.application.repository_provider import (
    get_portfolio_repository,
    get_dashboard_overview_repository,
)
from apps.dashboard.application.queries import DecisionPlaneData
from apps.dashboard.application.use_cases import GetDashboardDataUseCase

logger = logging.getLogger(__name__)

RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    ImportError,
    ImproperlyConfigured,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)


@dataclass(frozen=True)
class DashboardMacroComponents:
    """Dashboard macro widget payloads loaded from cross-app application services."""

    navigator: object | None = None
    pulse: object | None = None
    action: object | None = None


def _empty_decision_plane_data() -> DecisionPlaneData:
    """Return a safe fallback when decision-plane aggregation is unavailable."""
    return DecisionPlaneData(
        beta_gate_visible_classes="-",
        alpha_watch_count=0,
        alpha_candidate_count=0,
        alpha_actionable_count=0,
        quota_total=10,
        quota_used=0,
        quota_remaining=10,
        quota_usage_percent=0.0,
        actionable_candidates=[],
        pending_requests=[],
    )


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


def get_dashboard_alpha_refresh_celery_health() -> dict[str, object]:
    """Return whether dashboard Alpha async refresh currently has a live Celery worker."""
    try:
        from apps.task_monitor.application.repository_provider import get_celery_health_checker

        health = get_celery_health_checker().check_health()
        active_workers = list(getattr(health, "active_workers", []) or [])
        if active_workers and bool(getattr(health, "is_healthy", False)):
            return {"available": True, "active_workers": active_workers, "reason": "healthy"}
        if not active_workers:
            return {"available": False, "active_workers": [], "reason": "no_active_workers"}
        return {"available": False, "active_workers": active_workers, "reason": "unhealthy"}
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to inspect Celery health for dashboard alpha refresh: %s", exc)
        return {
            "available": False,
            "active_workers": [],
            "reason": "health_check_failed",
            "error": str(exc),
        }


def get_alpha_stock_scores_payload(
    *,
    top_n: int = 10,
    user=None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    alpha_scope: str | None = None,
    query_factory,
) -> dict[str, Any]:
    """Return Alpha stock items plus reliability metadata."""
    try:
        data = query_factory().execute(
            top_n=top_n,
            user=user,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            alpha_scope=alpha_scope,
        )
        meta = dict(data.meta)
        meta.setdefault("alpha_scope", alpha_scope)
        pool = dict(data.pool)
        pool.setdefault("alpha_scope", alpha_scope)
        return {
            "items": data.top_candidates,
            "meta": meta,
            "pool": pool,
            "actionable_candidates": data.actionable_candidates,
            "exit_watchlist": getattr(data, "exit_watchlist", []),
            "exit_watch_summary": getattr(data, "exit_watch_summary", {}),
            "pending_requests": data.pending_requests,
            "recent_runs": data.recent_runs,
            "history_run_id": data.history_run_id,
        }
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to get alpha stock scores payload: %s", exc)
        return {
            "items": [],
            "meta": {
                "status": "error",
                "source": "none",
                "warning_message": "alpha_stock_scores_unavailable",
                "is_degraded": True,
                "uses_cached_data": False,
                "alpha_scope": alpha_scope,
                "recommendation_ready": False,
                "must_not_use_for_decision": True,
            },
            "pool": {"alpha_scope": alpha_scope},
            "actionable_candidates": [],
            "exit_watchlist": [],
            "exit_watch_summary": {},
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": None,
        }


def get_portfolio_options(user_id: int) -> list[dict]:
    """Load user portfolio options for dashboard selectors."""
    return get_portfolio_repository().get_user_portfolios(user_id)


def get_valuation_repair_config_summary(*, use_cache: bool = False) -> dict | None:
    """Load valuation-repair config summary for dashboard widgets."""
    try:
        from apps.equity.application.config import (
            get_valuation_repair_config_summary as load_summary,
        )

        return load_summary(use_cache=use_cache)
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to get valuation repair config summary: %s", exc)
        return None


def load_phase1_macro_components(
    *,
    as_of_date: date | None = None,
    refresh_if_stale: bool = False,
) -> DashboardMacroComponents:
    """Load dashboard macro widgets via stable application-layer boundaries."""
    target_date = as_of_date or date.today()
    navigator = None
    pulse = None
    action = None

    try:
        from apps.regime.application.navigator_use_cases import BuildRegimeNavigatorUseCase

        navigator = BuildRegimeNavigatorUseCase().execute(target_date)
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to load regime navigator widget data: %s", exc)

    try:
        from apps.pulse.application.use_cases import GetLatestPulseUseCase

        pulse = GetLatestPulseUseCase().execute(
            as_of_date=target_date,
            refresh_if_stale=refresh_if_stale,
        )
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to load pulse widget data: %s", exc)

    try:
        from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase

        action = GetActionRecommendationUseCase().execute(
            target_date,
            refresh_pulse_if_stale=refresh_if_stale,
        )
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to load action recommendation widget data: %s", exc)

    return DashboardMacroComponents(
        navigator=navigator,
        pulse=pulse,
        action=action,
    )


def get_alpha_visualization_data(
    *,
    top_n: int = 10,
    ic_days: int = 30,
    user=None,
    query_factory,
):
    """Return the aggregated Alpha visualization payload with a single query execution."""
    try:
        return query_factory().execute(top_n=top_n, ic_days=ic_days, user=user)
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to get alpha visualization data: %s", exc)
        return None


def get_alpha_decision_chain_data(
    *,
    top_n: int = 10,
    ic_days: int = 30,
    max_candidates: int = 5,
    max_pending: int = 10,
    user=None,
    alpha_visualization_data=None,
    decision_plane_data=None,
    query_factory,
):
    """Return the unified Alpha decision-chain payload."""
    try:
        query = query_factory()
        if (
            alpha_visualization_data is not None
            and decision_plane_data is not None
            and hasattr(query, "build")
        ):
            return query.build(
                alpha_visualization_data=alpha_visualization_data,
                decision_plane_data=decision_plane_data,
            )
        return query.execute(
            top_n=top_n,
            ic_days=ic_days,
            max_candidates=max_candidates,
            max_pending=max_pending,
            user=user,
        )
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to get alpha decision chain data: %s", exc)
        return None


def load_alpha_factor_exposure(stock_code: str, provider: str, *, as_of_date) -> dict:
    """Load single-stock factor exposure from the Alpha provider registry."""
    try:
        from apps.alpha.application.services import AlphaService

        service = AlphaService()
        provider_instance = service._registry.get_provider(provider)
        if not provider_instance:
            return {}
        return provider_instance.get_factor_exposure(stock_code, as_of_date) or {}
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to load factor exposure for %s: %s", stock_code, exc)
        return {}


def get_decision_plane_data(
    *,
    max_candidates: int = 5,
    max_pending: int = 10,
    query_factory,
) -> DecisionPlaneData:
    """Return the aggregated decision-plane payload with a single query execution."""
    try:
        return query_factory().execute(max_candidates=max_candidates, max_pending=max_pending)
    except RECOVERABLE_DASHBOARD_INTERFACE_EXCEPTIONS as exc:
        logger.warning("Failed to get decision plane data: %s", exc)
        return _empty_decision_plane_data()


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
