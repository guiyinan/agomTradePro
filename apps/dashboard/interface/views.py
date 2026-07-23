"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- views.py 调用 Query Services 获取数据
- 隐藏 ORM 实现细节
"""

import logging
from collections.abc import Mapping
from time import perf_counter
from typing import Any

from celery.result import AsyncResult
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.alpha.application.ops_locks import (
    ALPHA_REFRESH_LOCK_TTL_SECONDS,
)
from apps.alpha.application.ops_locks import (
    acquire_dashboard_alpha_refresh_pending_lock as _acquire_dashboard_alpha_refresh_pending_lock,
)
from apps.alpha.application.ops_locks import (
    build_dashboard_alpha_refresh_metadata as _build_dashboard_alpha_refresh_metadata,
)
from apps.alpha.application.ops_locks import (
    promote_dashboard_alpha_refresh_task_lock as _promote_dashboard_alpha_refresh_task_lock,
)
from apps.alpha.application.ops_locks import (
    release_dashboard_alpha_refresh_lock as _release_dashboard_alpha_refresh_lock,
)
from apps.alpha.application.ops_locks import (
    resolve_dashboard_alpha_refresh_lock as _resolve_dashboard_alpha_refresh_lock_impl,
)
from apps.alpha.application.pool_resolver import (
    PortfolioAlphaPoolResolver as _PortfolioAlphaPoolResolver,
)
from apps.alpha.application.pool_resolver import (
    get_alpha_pool_mode_choices,
)
from apps.alpha.application.trade_dates import (
    resolve_recent_closed_trade_date as _resolve_dashboard_alpha_trade_date,
)
from apps.dashboard.application import interface_services as dashboard_interface_services
from apps.dashboard.application.alpha_homepage import (
    ALPHA_SCOPE_GENERAL,
    ALPHA_SCOPE_PORTFOLIO,
    normalize_alpha_scope,
)
from apps.dashboard.application.navigation import (
    build_decision_workspace_url as _build_decision_workspace_url,
)
from apps.dashboard.application.queries import (
    DecisionPlaneData,
    get_alpha_homepage_query,
    get_alpha_visualization_query,
    get_dashboard_detail_query,
    get_decision_plane_query,
)
from apps.dashboard.application.use_cases import DashboardData
from apps.dashboard.interface import (
    alpha_history_views,
    alpha_stock_views,
    dashboard_alpha_context,
    macro_views,
)
from apps.dashboard.interface.dashboard_alpha_context import (
    _annotate_alpha_exit_watchlist_navigation,
    _annotate_decision_workspace_navigation,
    _build_alpha_decision_chain_overview,
    _build_alpha_exit_detail_panel_context,
    _build_alpha_readiness_contract,
    _build_alpha_refresh_conflict_response,
    _build_alpha_refresh_lock_key,
    _build_dashboard_exit_detail_url,
    _build_dashboard_exit_entry_panel_context,
    _get_alpha_decision_chain_data,
    _get_alpha_stock_scores_payload,
    _get_dashboard_alpha_refresh_celery_health,
    _get_request_user_id,
    _log_dashboard_view_timing,
    _mark_alpha_exit_watchlist_selection,
    _should_render_alpha_top_candidates,
)
from apps.dashboard.interface.dashboard_regime_context import (
    _build_action_recommendation_context,
    _build_attention_items_context,
    _build_browser_notification_context,
    _build_market_thermometer_context,
    _build_pulse_card_context,
    _build_regime_status_context,
    _load_market_thermometer_payload,
    _load_phase1_macro_components,
    _normalize_dashboard_alpha_pool_mode,
    _parse_positive_int_param,
)
from core.integration.runtime_imports import record_pending_task

__all__ = [
    "ALPHA_SCOPE_GENERAL",
    "ALPHA_SCOPE_PORTFOLIO",
    "PortfolioAlphaPoolResolver",
    "_ALPHA_REFRESH_LOCK_TTL_SECONDS",
    "_annotate_alpha_exit_watchlist_navigation",
    "_annotate_decision_workspace_navigation",
    "_build_action_recommendation_context",
    "_build_alpha_exit_detail_panel_context",
    "_build_alpha_factor_panel",
    "_build_alpha_readiness_contract",
    "_build_alpha_refresh_conflict_response",
    "_build_alpha_refresh_lock_key",
    "_build_attention_items_context",
    "_build_dashboard_data",
    "_build_decision_workspace_url",
    "_build_dashboard_exit_detail_url",
    "_build_pulse_card_context",
    "_build_regime_status_context",
    "_ensure_dashboard_positions",
    "_get_alpha_decision_chain_data",
    "_get_alpha_stock_scores_payload",
    "_get_dashboard_alpha_refresh_celery_health",
    "_get_dashboard_portfolio_options",
    "_get_request_user_id",
    "_load_phase1_macro_components",
    "_load_simulated_positions_fallback",
    "_mark_alpha_exit_watchlist_selection",
    "_normalize_dashboard_alpha_pool_mode",
    "_parse_positive_int_param",
    "_resolve_existing_alpha_refresh_lock",
    "_should_render_alpha_top_candidates",
    "acquire_dashboard_alpha_refresh_pending_lock",
    "build_dashboard_alpha_refresh_metadata",
    "get_alpha_homepage_query",
    "get_alpha_visualization_query",
    "get_alpha_pool_mode_choices",
    "get_dashboard_detail_query",
    "get_decision_plane_query",
    "normalize_alpha_scope",
    "promote_dashboard_alpha_refresh_task_lock",
    "record_pending_task",
    "release_dashboard_alpha_refresh_lock",
    "resolve_dashboard_alpha_trade_date",
]

logger = logging.getLogger(__name__)
_ALPHA_REFRESH_LOCK_TTL_SECONDS = ALPHA_REFRESH_LOCK_TTL_SECONDS
_DASHBOARD_EXIT_DETAIL_ANCHOR = "alpha-exit-detail"
_DASHBOARD_VIEW_PERF_WARNING_MS = 4000
acquire_dashboard_alpha_refresh_pending_lock = _acquire_dashboard_alpha_refresh_pending_lock
PortfolioAlphaPoolResolver = _PortfolioAlphaPoolResolver
build_dashboard_alpha_refresh_metadata = _build_dashboard_alpha_refresh_metadata
promote_dashboard_alpha_refresh_task_lock = _promote_dashboard_alpha_refresh_task_lock
release_dashboard_alpha_refresh_lock = _release_dashboard_alpha_refresh_lock
resolve_dashboard_alpha_trade_date = _resolve_dashboard_alpha_trade_date


def _json_object(value: object) -> dict[str, Any]:
    """Normalize a dynamic template payload to a string-key mapping."""

    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _json_rows(value: object) -> list[dict[str, Any]]:
    """Normalize a dynamic template collection to JSON rows."""

    if not isinstance(value, (list, tuple)):
        return []
    return [_json_object(item) for item in value if isinstance(item, Mapping)]


def _build_dashboard_data(user_id: int) -> DashboardData:
    """Build dashboard DTO for API and page views."""
    return dashboard_interface_services.build_dashboard_data(user_id)


def _load_simulated_positions_fallback(
    user_id: int,
    account_id: int | None = None,
) -> list[dict[str, Any]]:
    """Read holdings directly from the current simulated-account tables.

    Args:
        user_id: The user whose positions to load.
        account_id: Optional account ID to filter positions by a specific account.
    """
    return _json_rows(
        dashboard_interface_services.load_simulated_positions_fallback(
            user_id=user_id,
            account_id=account_id,
        )
    )


def _get_dashboard_accounts(user: Any) -> list[dict[str, Any]]:
    """Load all user investment accounts for dashboard cards."""
    return _json_rows(dashboard_interface_services.get_dashboard_accounts(user))


def _ensure_dashboard_positions(
    data: DashboardData,
    user_id: int,
) -> DashboardData:
    """Backfill positions for page/HTMX rendering when portfolio snapshot is stale."""
    return dashboard_interface_services.ensure_dashboard_positions(data, user_id)


def _get_dashboard_portfolio_options(user_id: int) -> list[dict[str, Any]]:
    """Load dashboard portfolio choices with a database-only fallback."""
    try:
        return _json_rows(dashboard_interface_services.get_portfolio_options(user_id))
    except DatabaseError as exc:
        logger.warning("Failed to get portfolio options: %s", exc)
        return []


def _get_dashboard_valuation_repair_config_summary() -> dict[str, Any] | None:
    """Load valuation-repair config summary through the dashboard application boundary."""
    summary = dashboard_interface_services.get_valuation_repair_config_summary(use_cache=False)
    return _json_object(summary) if summary is not None else None


def _get_alpha_metrics_data(ic_days: int = 30) -> Any:
    """Load Alpha metrics through the legacy query-factory patch surface."""

    from apps.dashboard.interface.alpha_metrics_views import get_alpha_metrics_data

    return get_alpha_metrics_data(
        ic_days=ic_days,
        query_factory=get_alpha_visualization_query,
    )


def _get_decision_plane_data(
    max_candidates: int = 5,
    max_pending: int = 10,
) -> DecisionPlaneData:
    """Load decision-plane data through the legacy query-factory patch surface."""

    return dashboard_interface_services.get_decision_plane_data(
        max_candidates=max_candidates,
        max_pending=max_pending,
        query_factory=get_decision_plane_query,
    )


def _resolve_existing_alpha_refresh_lock(lock_key: str) -> Any:
    """Resolve Alpha refresh locks using the legacy AsyncResult patch surface."""

    return _resolve_dashboard_alpha_refresh_lock_impl(
        lock_key,
        async_result_cls=AsyncResult,
    )


def _build_alpha_factor_panel(
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build factor context while honoring the legacy score-loader patch surface."""

    kwargs.setdefault("stock_scores_loader", _get_alpha_stock_scores_payload)
    panel = dashboard_alpha_context._build_alpha_factor_panel(*args, **kwargs)
    return _json_object(panel)


@login_required(login_url="/account/login/")
def dashboard_entry(request: HttpRequest) -> HttpResponse:
    """
    Dashboard entrypoint.

    If Streamlit dashboard is enabled, redirect to Streamlit URL.
    Otherwise fall back to legacy Django dashboard page.
    """
    if bool(getattr(settings, "STREAMLIT_DASHBOARD_ENABLED", False)):
        return redirect(str(getattr(settings, "STREAMLIT_DASHBOARD_URL", "/")))
    return dashboard_view(request)


@login_required(login_url="/account/login/")
def dashboard_view(request: HttpRequest) -> HttpResponse:
    """
    首页仪表盘视图

    展示：
    1. 宏观环境快照（当前Regime）
    2. 我的资产总览
    3. 当前持仓列表
    4. 我的投资信号
    5. AI操作建议
    """
    request_started_at = perf_counter()
    step_durations_ms: dict[str, int] = {}
    user_id = _get_request_user_id(request.user)
    if user_id is None:
        raise PermissionDenied("A persisted user is required for the dashboard.")

    def _track_step(step_name: str, step_started_at: float) -> None:
        step_durations_ms[step_name] = int((perf_counter() - step_started_at) * 1000)

    # 获取首页数据
    step_started_at = perf_counter()
    data = _build_dashboard_data(user_id)
    _track_step("build_dashboard_data", step_started_at)

    step_started_at = perf_counter()
    data = _ensure_dashboard_positions(data, user_id)
    _track_step("ensure_positions", step_started_at)

    step_started_at = perf_counter()
    navigator, pulse, action = _load_phase1_macro_components()
    _track_step("macro_components", step_started_at)

    # 补充用户名
    data.username = str(getattr(request.user, "username", ""))
    raw_portfolio_id = request.GET.get("portfolio_id")
    selected_portfolio_id: int | None
    if raw_portfolio_id not in (None, ""):
        try:
            selected_portfolio_id = _parse_positive_int_param(
                raw_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
        except ValueError:
            selected_portfolio_id = None
    else:
        selected_portfolio_id = None
    selected_alpha_pool_mode = _normalize_dashboard_alpha_pool_mode(request.GET.get("pool_mode"))
    portfolio_options = _get_dashboard_portfolio_options(user_id)
    requested_alpha_scope = request.GET.get("alpha_scope")
    selected_alpha_scope = normalize_alpha_scope(requested_alpha_scope)
    selected_exit_asset_code = str(request.GET.get("exit_asset_code") or "").strip().upper() or None
    raw_exit_account_id = request.GET.get("exit_account_id")
    try:
        selected_exit_account_id = (
            _parse_positive_int_param(raw_exit_account_id, field_name="exit_account_id", default=0)
            if raw_exit_account_id not in (None, "")
            else None
        )
    except ValueError:
        selected_exit_account_id = None
    if (
        requested_alpha_scope in (None, "")
        and not portfolio_options
        and selected_portfolio_id is None
    ):
        selected_alpha_scope = ALPHA_SCOPE_GENERAL

    step_started_at = perf_counter()
    decision_plane_data = _get_decision_plane_data(max_candidates=5, max_pending=10)
    _track_step("decision_plane", step_started_at)

    step_started_at = perf_counter()
    alpha_metrics_data = _get_alpha_metrics_data(ic_days=30)
    _track_step("alpha_metrics", step_started_at)

    step_started_at = perf_counter()
    investment_accounts = _get_dashboard_accounts(request.user)
    _track_step("investment_accounts", step_started_at)

    step_started_at = perf_counter()
    valuation_repair_config_summary = _get_dashboard_valuation_repair_config_summary()
    _track_step("valuation_repair_summary", step_started_at)

    step_started_at = perf_counter()
    market_thermometer_payload = _load_market_thermometer_payload(user_id)
    _track_step("market_thermometer", step_started_at)

    step_started_at = perf_counter()
    context = _build_dashboard_page_context(
        request=request,
        data=data,
        navigator=navigator,
        pulse=pulse,
        action=action,
        portfolio_options=portfolio_options,
        investment_accounts=investment_accounts,
        selected_portfolio_id=selected_portfolio_id,
        selected_alpha_pool_mode=selected_alpha_pool_mode,
        selected_alpha_scope=selected_alpha_scope,
        decision_plane_data=decision_plane_data,
        alpha_metrics_data=alpha_metrics_data,
        valuation_repair_config_summary=valuation_repair_config_summary,
        selected_exit_asset_code=selected_exit_asset_code,
        selected_exit_account_id=selected_exit_account_id,
        market_thermometer_payload=market_thermometer_payload,
    )
    _track_step("build_context", step_started_at)

    step_started_at = perf_counter()
    response = render(request, "dashboard/index.html", context)
    _track_step("render", step_started_at)

    total_duration_ms = int((perf_counter() - request_started_at) * 1000)
    _log_dashboard_view_timing(
        "Dashboard page request completed",
        duration_ms=total_duration_ms,
        user_id=_get_request_user_id(request.user),
        portfolio_id=selected_portfolio_id,
        alpha_scope=selected_alpha_scope,
        pool_mode=selected_alpha_pool_mode,
        exit_asset_code=selected_exit_asset_code,
        exit_account_id=selected_exit_account_id,
        step_durations_ms=step_durations_ms,
        position_count=len(getattr(data, "positions", []) or []),
        investment_account_count=len(investment_accounts),
        alpha_candidate_count=len(context.get("alpha_stock_scores", []) or []),
        alpha_actionable_count=len(context.get("alpha_actionable_candidates", []) or []),
        alpha_pending_count=len(context.get("alpha_pending_requests", []) or []),
        workflow_actionable_count=len(
            getattr(decision_plane_data, "actionable_candidates", []) or []
        ),
        workflow_pending_count=len(getattr(decision_plane_data, "pending_requests", []) or []),
    )

    return response


def _build_dashboard_page_context(
    *,
    request: HttpRequest,
    data: DashboardData,
    navigator: Any,
    pulse: Any,
    action: Any,
    portfolio_options: list[dict[str, Any]],
    investment_accounts: list[dict[str, Any]],
    selected_portfolio_id: int | None,
    selected_alpha_pool_mode: str,
    selected_alpha_scope: str,
    decision_plane_data: DecisionPlaneData,
    alpha_metrics_data: Any,
    valuation_repair_config_summary: dict[str, Any] | None,
    selected_exit_asset_code: str | None,
    selected_exit_account_id: int | None,
    market_thermometer_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the dashboard template context from already-loaded read models."""
    raw_alpha_stock_scores: list[dict[str, Any]] = []
    alpha_stock_scores: list[dict[str, Any]] = []
    alpha_stock_scores_meta: dict[str, Any] = {}
    alpha_actionable_candidates: list[dict[str, Any]] = []
    alpha_exit_watchlist: list[dict[str, Any]] = []
    alpha_exit_watch_summary: dict[str, Any] = {"total": 0}
    alpha_pending_requests: list[dict[str, Any]] = []
    alpha_pool: dict[str, Any] = {
        "portfolio_id": selected_portfolio_id,
        "pool_mode": selected_alpha_pool_mode,
        "label": "Alpha 排名入口",
        "pool_size": 0,
    }
    alpha_recent_runs: list[dict[str, Any]] = []
    alpha_history_run_id: int | None = None
    try:
        alpha_payload = _get_alpha_stock_scores_payload(
            top_n=10,
            user=request.user,
            portfolio_id=(
                None if selected_alpha_scope == ALPHA_SCOPE_GENERAL else selected_portfolio_id
            ),
            pool_mode=selected_alpha_pool_mode,
            alpha_scope=selected_alpha_scope,
        )
    except Exception as exc:
        logger.warning("Failed to build homepage alpha payload: %s", exc, exc_info=True)
    else:
        alpha_stock_scores_meta = dict(alpha_payload.get("meta") or {})
        alpha_pool.update(dict(alpha_payload.get("pool") or {}))
        raw_effective_portfolio_id = (
            None
            if selected_alpha_scope == ALPHA_SCOPE_GENERAL
            else selected_portfolio_id or alpha_pool.get("portfolio_id")
        )
        try:
            effective_alpha_portfolio_id = (
                _parse_positive_int_param(
                    raw_effective_portfolio_id,
                    field_name="portfolio_id",
                    default=0,
                )
                if raw_effective_portfolio_id not in (None, "")
                else None
            )
        except ValueError:
            effective_alpha_portfolio_id = None
        raw_alpha_stock_scores = _annotate_decision_workspace_navigation(
            list(alpha_payload.get("items") or []),
            source="dashboard-alpha",
            security_code_key="code",
            view_step=None,
            primary_step=4,
        )
        alpha_stock_scores = raw_alpha_stock_scores
        alpha_actionable_candidates = _annotate_decision_workspace_navigation(
            list(alpha_payload.get("actionable_candidates") or []),
            source="dashboard-alpha-actionable",
            security_code_key="code",
            view_step=None,
            primary_step=4,
        )
        alpha_pending_requests = _annotate_decision_workspace_navigation(
            list(alpha_payload.get("pending_requests") or []),
            source="dashboard-alpha-pending",
            security_code_key="code",
            view_step=5,
            primary_step=5,
        )
        alpha_exit_watchlist = _mark_alpha_exit_watchlist_selection(
            _annotate_alpha_exit_watchlist_navigation(
                list(alpha_payload.get("exit_watchlist") or []),
                alpha_scope=selected_alpha_scope,
                portfolio_id=effective_alpha_portfolio_id,
            ),
            account_id=selected_exit_account_id,
            asset_code=selected_exit_asset_code,
        )
        alpha_exit_watch_summary = dict(
            alpha_payload.get("exit_watch_summary") or {"total": len(alpha_exit_watchlist)}
        )
        alpha_recent_runs = list(alpha_payload.get("recent_runs") or [])
        alpha_history_run_id = alpha_payload.get("history_run_id")
    alpha_exit_entry_panel = _build_dashboard_exit_entry_panel_context(alpha_exit_watchlist)
    alpha_exit_detail_panel = _build_alpha_exit_detail_panel_context(
        exit_watchlist=alpha_exit_watchlist,
        account_id=selected_exit_account_id,
        asset_code=selected_exit_asset_code,
    )
    alpha_decision_chain_overview = _build_alpha_decision_chain_overview(
        top_candidates=raw_alpha_stock_scores,
        actionable_candidates=alpha_actionable_candidates,
        pending_requests=alpha_pending_requests,
    )
    workflow_actionable_candidates = _annotate_decision_workspace_navigation(
        decision_plane_data.actionable_candidates,
        source="dashboard-workflow",
        security_code_key="asset_code",
        view_step=None,
        primary_step=4,
    )
    workflow_pending_requests = _annotate_decision_workspace_navigation(
        decision_plane_data.pending_requests,
        source="dashboard-pending",
        security_code_key="asset_code",
        view_step=5,
        primary_step=5,
    )
    context: dict[str, Any] = {
        "user": request.user,
        "display_name": data.display_name,
        # 宏观环境
        "current_regime": data.current_regime,
        "regime_date": data.regime_date,
        "regime_confidence": data.regime_confidence,
        "regime_confidence_pct": data.regime_confidence * 100,
        "growth_momentum_z": data.growth_momentum_z,
        "inflation_momentum_z": data.inflation_momentum_z,
        "regime_distribution": data.regime_distribution,
        "regime_data_health": data.regime_data_health,
        "regime_warnings": data.regime_warnings,
        "pmi_value": data.pmi_value,
        "cpi_value": data.cpi_value,
        # 政策档位
        "policy_level": data.current_policy_level,
        # 资产总览
        "total_assets": data.total_assets,
        "initial_capital": data.initial_capital,
        "total_return": data.total_return,
        "total_return_pct": data.total_return_pct,
        "investment_accounts": investment_accounts,
        "portfolio_options": portfolio_options,
        "cash_balance": data.cash_balance,
        "invested_value": data.invested_value,
        "invested_ratio": data.invested_ratio,
        # 持仓
        "positions": data.positions,
        "position_count": data.position_count,
        "regime_match_score": data.regime_match_score,
        "regime_recommendations": data.regime_recommendations,
        # 信号
        "active_signals": data.active_signals,
        "signal_stats": data.signal_stats,
        # 资产配置
        "asset_allocation": data.asset_allocation,
        # AI建议
        "ai_insights": data.ai_insights,
        # 资产配置建议（新增）
        "allocation_advice": data.allocation_advice,
        # 新增：图表数据
        "allocation_data": data.allocation_data if hasattr(data, "allocation_data") else {},
        "performance_data": data.performance_data if hasattr(data, "performance_data") else [],
        # 决策平面数据（新增）
        "beta_gate_visible_classes": decision_plane_data.beta_gate_visible_classes,
        "alpha_watch_count": decision_plane_data.alpha_watch_count,
        "alpha_candidate_count": decision_plane_data.alpha_candidate_count,
        "alpha_actionable_count": decision_plane_data.alpha_actionable_count,
        "quota_total": decision_plane_data.quota_total,
        "quota_used": decision_plane_data.quota_used,
        "quota_remaining": decision_plane_data.quota_remaining,
        "quota_usage_percent": decision_plane_data.quota_usage_percent,
        "actionable_candidates": workflow_actionable_candidates,
        "pending_requests": workflow_pending_requests,
        "pending_count": len(workflow_pending_requests),
        "alpha_decision_chain_overview": alpha_decision_chain_overview,
        # Alpha 可视化数据（新增）
        "alpha_stock_scores": alpha_stock_scores,
        "alpha_research_rankings": raw_alpha_stock_scores,
        "alpha_stock_scores_meta": alpha_stock_scores_meta,
        "alpha_actionable_candidates": alpha_actionable_candidates,
        "alpha_exit_watchlist": alpha_exit_watchlist,
        "alpha_exit_watch_summary": alpha_exit_watch_summary,
        "alpha_exit_entry_watchlist": alpha_exit_entry_panel["items"],
        "alpha_exit_entry_watch_summary": alpha_exit_entry_panel["summary"],
        "alpha_exit_entry_hidden_count": alpha_exit_entry_panel["hidden_processed_count"],
        "alpha_exit_detail_panel": alpha_exit_detail_panel,
        "alpha_exit_selected_asset_code": (
            alpha_exit_detail_panel.get("selected", {}).get("asset_code")
            if alpha_exit_detail_panel.get("selected")
            else ""
        ),
        "alpha_exit_selected_account_id": (
            alpha_exit_detail_panel.get("selected", {}).get("account_id")
            if alpha_exit_detail_panel.get("selected")
            else ""
        ),
        "alpha_pending_requests": alpha_pending_requests,
        "alpha_pool": alpha_pool,
        "alpha_recent_runs": alpha_recent_runs,
        "alpha_history_run_id": alpha_history_run_id,
        "selected_portfolio_id": selected_portfolio_id,
        "selected_alpha_pool_mode": selected_alpha_pool_mode,
        "selected_alpha_scope": selected_alpha_scope,
        "alpha_pool_mode_choices": get_alpha_pool_mode_choices(),
        "alpha_provider_status": alpha_metrics_data.provider_status,
        "alpha_coverage_metrics": alpha_metrics_data.coverage_metrics,
        "alpha_ic_trends": alpha_metrics_data.ic_trends,
        "alpha_factor_panel": None,
        "valuation_repair_config_summary": valuation_repair_config_summary,
    }
    context.update(_build_regime_status_context(navigator, pulse, action))
    context.update(_build_pulse_card_context(pulse))
    context.update(_build_market_thermometer_context(market_thermometer_payload))
    context.update(_build_action_recommendation_context(action))
    context.update(
        _build_attention_items_context(data, navigator, pulse, market_thermometer_payload)
    )
    context.update(_build_browser_notification_context(navigator, pulse))
    return context


# ========================================
# 决策平面数据获取辅助函数（委托至 Query Services）
# ========================================

# Legacy public entries remain here so existing imports and monkeypatch paths keep working.
alpha_refresh_htmx = alpha_stock_views.alpha_refresh_htmx
alpha_stocks_htmx = alpha_stock_views.alpha_stocks_htmx
alpha_history_list_api = alpha_history_views.alpha_history_list_api
alpha_history_detail_api = alpha_history_views.alpha_history_detail_api
action_recommendation_htmx = macro_views.action_recommendation_htmx
