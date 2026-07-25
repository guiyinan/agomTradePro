"""Dashboard empty-state and decision-plane navigation helpers."""

import logging
from typing import Any

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
from apps.alpha.application.pool_resolver import (
    PortfolioAlphaPoolResolver as _PortfolioAlphaPoolResolver,
)
from apps.alpha.application.trade_dates import (
    resolve_recent_closed_trade_date as _resolve_dashboard_alpha_trade_date,
)
from apps.dashboard.application import interface_services as dashboard_interface_services
from apps.dashboard.application.queries import (
    DecisionPlaneData,
    get_decision_plane_query,
)
from apps.dashboard.interface import (
    alpha_history_views,
    alpha_stock_views,
    api_v1_views,
    macro_views,
    portfolio_views,
    workflow_views,
)

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


def _empty_decision_plane_data() -> DecisionPlaneData:
    """Return a safe fallback when decision-plane aggregation is unavailable."""
    return DecisionPlaneData(
        beta_gate_visible_classes="-",
        alpha_watch_count=0,
        alpha_candidate_count=0,
        alpha_actionable_count=0,
        quota_total=0,
        quota_used=0,
        quota_remaining=0,
        quota_usage_percent=0.0,
        actionable_candidates=[],
        pending_requests=[],
        quota_available=False,
    )


def _get_beta_gate_visible_classes() -> str:
    """
    获取 Beta Gate 允许的可见资产类别

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data().beta_gate_visible_classes


def _get_alpha_status_count(status: str) -> int:
    """
    获取 Alpha 候选状态计数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    data = _get_decision_plane_data()
    if status == "WATCH":
        return data.alpha_watch_count
    if status == "CANDIDATE":
        return data.alpha_candidate_count
    if status == "ACTIONABLE":
        return data.alpha_actionable_count
    return 0


def _get_quota_total() -> int:
    """
    获取决策配额总数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data().quota_total


def _get_quota_used() -> int:
    """
    获取已使用的决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data().quota_used


def _get_quota_remaining() -> int:
    """
    获取剩余决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data().quota_remaining


def _get_quota_usage_percent() -> float:
    """
    获取决策配额使用百分比

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data().quota_usage_percent


def _get_actionable_candidates() -> list[Any]:
    """
    首页主流程展示：可操作候选列表（含估值修复信息）

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data(
        max_candidates=5,
        max_pending=10,
    ).actionable_candidates


def _get_pending_requests() -> list[Any]:
    """
    首页主流程展示：已批准但未执行/失败待重试请求

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data(max_candidates=5, max_pending=10).pending_requests


def _get_pending_count() -> int:
    return len(_get_pending_requests())


def _get_decision_plane_data(
    max_candidates: int = 5,
    max_pending: int = 10,
) -> DecisionPlaneData:
    """Return the aggregated decision-plane payload with a single query execution."""
    data = dashboard_interface_services.get_decision_plane_data(
        max_candidates=max_candidates,
        max_pending=max_pending,
        query_factory=get_decision_plane_query,
    )
    return data


workflow_refresh_candidates = workflow_views.workflow_refresh_candidates
regime_status_htmx = macro_views.regime_status_htmx
pulse_card_htmx = macro_views.pulse_card_htmx
action_recommendation_htmx = macro_views.action_recommendation_htmx
attention_items_htmx = macro_views.attention_items_htmx
position_detail_htmx = portfolio_views.position_detail_htmx
positions_list_htmx = portfolio_views.positions_list_htmx
allocation_chart_htmx = portfolio_views.allocation_chart_htmx
performance_chart_htmx = portfolio_views.performance_chart_htmx


# ========================================
# Alpha 可视化 HTMX 视图
# ========================================

alpha_history_page = alpha_history_views.alpha_history_page
alpha_history_list_api = alpha_history_views.alpha_history_list_api
alpha_history_detail_api = alpha_history_views.alpha_history_detail_api
alpha_refresh_htmx = alpha_stock_views.alpha_refresh_htmx
alpha_stocks_htmx = alpha_stock_views.alpha_stocks_htmx


alpha_factor_panel_htmx = alpha_stock_views.alpha_factor_panel_htmx
dashboard_summary_v1 = api_v1_views.dashboard_summary_v1
regime_quadrant_v1 = api_v1_views.regime_quadrant_v1
equity_curve_v1 = api_v1_views.equity_curve_v1
signal_status_v1 = api_v1_views.signal_status_v1
alpha_decision_chain_v1 = api_v1_views.alpha_decision_chain_v1
