"""Alpha metrics, factor, exit, and navigation context helpers."""

# ruff: noqa: I001

import logging
from collections.abc import Mapping
from datetime import date
from urllib.parse import urlencode

from celery.result import AsyncResult
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone as django_timezone

from apps.alpha.application.ops_locks import (
    ALPHA_REFRESH_LOCK_TTL_SECONDS,
)
from apps.alpha.application.ops_locks import (
    acquire_dashboard_alpha_refresh_pending_lock as _acquire_dashboard_alpha_refresh_pending_lock,
)
from apps.alpha.application.ops_locks import (
    build_dashboard_alpha_refresh_lock_key as _shared_build_alpha_refresh_lock_key,
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
    resolve_dashboard_alpha_refresh_lock,
)
from apps.alpha.application.pool_resolver import (
    PortfolioAlphaPoolResolver as _PortfolioAlphaPoolResolver,
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
from apps.dashboard.application.navigation import (
    build_exit_user_action_label as _build_exit_user_action_label,
)
from apps.dashboard.application.navigation import (
    normalize_exit_user_action as _normalize_exit_user_action,
)
from apps.dashboard.application.queries import (
    get_alpha_decision_chain_query,
    get_alpha_homepage_query,
    get_alpha_visualization_query,
)
from apps.dashboard.interface import (
    alpha_metrics_views,
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


def _get_request_user_id(user) -> int | None:
    """Return a stable numeric user identifier when available."""
    user_id = getattr(user, "id", None)
    if user_id in (None, ""):
        user_id = getattr(user, "pk", None)
    try:
        return int(user_id) if user_id not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _log_dashboard_view_timing(
    message: str,
    *,
    duration_ms: int,
    **extra_fields: object,
) -> None:
    """Emit structured timing logs for the dashboard page request."""
    log_method = logger.warning if duration_ms >= _DASHBOARD_VIEW_PERF_WARNING_MS else logger.info
    log_method(
        message,
        extra={
            "event": "dashboard_view_completed",
            "duration_ms": duration_ms,
            **extra_fields,
        },
    )


def _clone_dashboard_item(item: object) -> dict[str, object]:
    """Normalize dashboard items from dict-like payloads or model objects."""

    if isinstance(item, Mapping):
        return dict(item)

    try:
        item_vars = vars(item)
    except TypeError:
        return {}

    return {key: value for key, value in item_vars.items() if not key.startswith("_")}


def _get_dashboard_alpha_refresh_celery_health() -> dict[str, object]:
    """Return whether dashboard Alpha async refresh currently has a live Celery worker."""
    return dashboard_interface_services.get_dashboard_alpha_refresh_celery_health()


def _build_alpha_refresh_lock_key(
    *,
    alpha_scope: str,
    target_date: date,
    top_n: int,
    raw_universe_id: str,
    resolved_pool=None,
) -> str:
    """Build a stable lock key for one dashboard alpha refresh scope."""
    return _shared_build_alpha_refresh_lock_key(
        alpha_scope=alpha_scope,
        target_date=target_date,
        top_n=top_n,
        raw_universe_id=raw_universe_id,
        resolved_pool=resolved_pool,
    )


def _resolve_existing_alpha_refresh_lock(lock_key: str) -> dict[str, object] | None:
    """Return active lock metadata, clearing stale async locks automatically."""
    return resolve_dashboard_alpha_refresh_lock(lock_key, async_result_cls=AsyncResult)


def _build_alpha_refresh_conflict_response(
    *,
    alpha_scope: str,
    target_date: date,
    top_n: int,
    universe_id: str,
    portfolio_id: int | None,
    pool_mode: str,
    lock_meta: dict[str, object],
):
    """Return a consistent conflict response for duplicate dashboard alpha refresh requests."""
    task_id = lock_meta.get("task_id")
    task_state = lock_meta.get("task_state")
    mode = lock_meta.get("mode")
    return JsonResponse(
        {
            "success": False,
            "error": "当前 Alpha 推理仍在进行中，请等待完成后再重试。",
            "alpha_scope": alpha_scope,
            "task_id": task_id,
            "task_state": task_state,
            "universe_id": universe_id,
            "portfolio_id": portfolio_id,
            "pool_mode": pool_mode,
            "requested_trade_date": target_date.isoformat(),
            "top_n": top_n,
            "refresh_status": "running",
            "sync": mode == "sync",
            "must_not_use_for_decision": True,
            "poll_after_ms": 3000,
        },
        status=409,
    )


def _build_alpha_decision_chain_overview(
    top_candidates: list[dict],
    actionable_candidates: list[dict],
    pending_requests: list[dict],
) -> dict:
    """Build workflow summary counts from the account-driven Alpha payload."""
    top_ranked_count = len(top_candidates)
    top10_actionable_count = sum(1 for item in top_candidates if item.get("stage") == "actionable")
    top10_pending_count = sum(1 for item in top_candidates if item.get("stage") == "pending")
    top10_rank_only_count = max(top_ranked_count - top10_actionable_count - top10_pending_count, 0)
    actionable_outside_top10_count = max(len(actionable_candidates) - top10_actionable_count, 0)
    pending_outside_top10_count = max(len(pending_requests) - top10_pending_count, 0)
    actionable_total = top10_actionable_count + actionable_outside_top10_count
    pending_total = top10_pending_count + pending_outside_top10_count
    denominator = top_ranked_count or 1
    return {
        "top_ranked_count": top_ranked_count,
        "actionable_count": actionable_total,
        "pending_count": pending_total,
        "top10_actionable_count": top10_actionable_count,
        "top10_pending_count": top10_pending_count,
        "top10_rank_only_count": top10_rank_only_count,
        "actionable_outside_top10_count": actionable_outside_top10_count,
        "pending_outside_top10_count": pending_outside_top10_count,
        "actionable_conversion_pct": round((actionable_total / denominator) * 100, 2),
        "pending_conversion_pct": round((pending_total / denominator) * 100, 2),
    }


def _build_alpha_readiness_contract(
    *,
    meta: dict,
    top_candidates: list[dict],
    actionable_candidates: list[dict],
    pending_requests: list[dict],
) -> dict:
    """Build a decision-safety contract for dashboard Alpha payloads."""
    refresh_status = str(meta.get("refresh_status") or "")
    async_task_id = str(meta.get("async_task_id") or "")
    recommendation_ready = bool(meta.get("recommendation_ready", False))
    blocked_reason = str(meta.get("blocked_reason") or meta.get("no_recommendation_reason") or "")
    return {
        "alpha_scope": str(meta.get("alpha_scope") or ALPHA_SCOPE_PORTFOLIO),
        "recommendation_ready": recommendation_ready,
        "must_not_treat_as_recommendation": not recommendation_ready,
        "must_not_use_for_decision": not recommendation_ready,
        "readiness_status": str(meta.get("readiness_status") or ""),
        "blocked_reason": blocked_reason,
        "async_refresh_queued": DashboardModuleContract._is_async_refresh_active(
            refresh_status=refresh_status,
            async_task_id=async_task_id,
        ),
        "refresh_status": refresh_status,
        "async_task_id": async_task_id,
        "poll_after_ms": DashboardModuleContract._safe_int(meta.get("poll_after_ms"), default=5000),
        "hardcoded_fallback_used": bool(meta.get("hardcoded_fallback_used", False)),
        "no_recommendation_reason": str(meta.get("no_recommendation_reason") or ""),
        "top_candidate_count": len(top_candidates),
        "actionable_candidate_count": len(actionable_candidates),
        "pending_request_count": len(pending_requests),
        "source": str(meta.get("source") or ""),
        "status": str(meta.get("status") or ""),
        "scope_hash": str(meta.get("scope_hash") or ""),
        "scope_verification_status": str(meta.get("scope_verification_status") or ""),
        "freshness_status": str(meta.get("freshness_status") or ""),
        "result_age_days": meta.get("result_age_days"),
        "is_stale": bool(meta.get("is_stale", False)),
        "latest_available_qlib_result": bool(meta.get("latest_available_qlib_result", False)),
        "derived_from_broader_cache": bool(meta.get("derived_from_broader_cache", False)),
        "trade_date_adjusted": bool(meta.get("trade_date_adjusted", False)),
        "verified_scope_hash": str(meta.get("verified_scope_hash") or ""),
        "verified_asof_date": meta.get("verified_asof_date"),
    }


def _should_render_alpha_top_candidates(*, meta: dict, alpha_scope: str) -> bool:
    """Return whether Alpha top candidates may be rendered as visible rankings."""

    normalized_alpha_scope = normalize_alpha_scope(alpha_scope)
    if normalized_alpha_scope == ALPHA_SCOPE_GENERAL:
        return True
    return bool(meta.get("recommendation_ready", False))


class DashboardModuleContract:
    """Shared helpers for dashboard readiness contract formatting."""

    @staticmethod
    def _safe_int(value, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_async_refresh_active(refresh_status: str, async_task_id: str) -> bool:
        status = refresh_status.lower()
        if status in {"queued", "recently_queued", "pending", "running", "started"}:
            return True
        if status in {"failed", "skipped", "available", "completed", "success", "done"}:
            return False
        return bool(async_task_id)


def _get_alpha_stock_scores_payload(
    top_n: int = 10,
    user=None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    alpha_scope: str | None = None,
) -> dict:
    """Return Alpha stock items plus reliability metadata."""
    normalized_alpha_scope = normalize_alpha_scope(alpha_scope)
    return dashboard_interface_services.get_alpha_stock_scores_payload(
        top_n=top_n,
        user=user,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=normalized_alpha_scope,
        query_factory=get_alpha_homepage_query,
    )


def _get_alpha_visualization_data(top_n: int = 10, ic_days: int = 30, user=None):
    """Return the aggregated Alpha visualization payload with a single query execution."""
    return dashboard_interface_services.get_alpha_visualization_data(
        top_n=top_n,
        ic_days=ic_days,
        user=user,
        query_factory=get_alpha_visualization_query,
    )


def _get_empty_alpha_metrics_data():
    """Return empty Alpha metrics for degraded dashboard rendering."""
    return alpha_metrics_views.get_empty_alpha_metrics_data()


def _get_alpha_metrics_data(ic_days: int = 30):
    """Return Alpha dashboard metrics without reloading stock recommendations."""
    return alpha_metrics_views.get_alpha_metrics_data(
        ic_days=ic_days,
        query_factory=get_alpha_visualization_query,
    )


def _get_alpha_stock_scores(
    top_n: int = 10,
    user=None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    alpha_scope: str | None = None,
) -> list:
    """
    获取 Alpha 选股评分结果

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    - 隐藏跨模块导入细节
    """
    return _get_alpha_stock_scores_payload(
        top_n=top_n,
        user=user,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )["items"]


def _get_alpha_stock_scores_meta(
    top_n: int = 10,
    user=None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    alpha_scope: str | None = None,
) -> dict:
    """Return stock-score reliability metadata for dashboard rendering."""
    return _get_alpha_stock_scores_payload(
        top_n=top_n,
        user=user,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )["meta"]


def _get_alpha_provider_status(user=None) -> dict:
    """
    获取 Alpha Provider 状态

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    return alpha_metrics_views.get_alpha_provider_status(
        user=user,
        query_factory=get_alpha_visualization_query,
    )


def _get_alpha_coverage_metrics(user=None) -> dict:
    """
    获取 Alpha 覆盖率指标

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    return alpha_metrics_views.get_alpha_coverage_metrics(
        user=user,
        query_factory=get_alpha_visualization_query,
    )


def _get_alpha_ic_trends_payload(days: int = 30, user=None) -> dict:
    """
    获取 Alpha IC/ICIR 趋势数据

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    return alpha_metrics_views.get_alpha_ic_trends_payload(
        days=days,
        user=user,
        query_factory=get_alpha_visualization_query,
    )


def _get_alpha_ic_trends(days: int = 30, user=None) -> list:
    return alpha_metrics_views.get_alpha_ic_trends(
        days=days,
        user=user,
        query_factory=get_alpha_visualization_query,
    )


def _get_alpha_decision_chain_data(
    top_n: int = 10,
    ic_days: int = 30,
    max_candidates: int = 5,
    max_pending: int = 10,
    user=None,
    alpha_visualization_data=None,
    decision_plane_data=None,
):
    """Return the unified Alpha decision-chain payload."""
    return dashboard_interface_services.get_alpha_decision_chain_data(
        top_n=top_n,
        ic_days=ic_days,
        max_candidates=max_candidates,
        max_pending=max_pending,
        user=user,
        alpha_visualization_data=alpha_visualization_data,
        decision_plane_data=decision_plane_data,
        query_factory=get_alpha_decision_chain_query,
    )


def _build_alpha_factor_panel(
    stock_code: str,
    source: str | None = None,
    top_n: int = 10,
    scores: list[dict] | None = None,
    user=None,
    portfolio_id: int | None = None,
    pool_mode: str | None = None,
    alpha_scope: str | None = None,
    load_provider_factors: bool = True,
    stock_scores_loader=None,
) -> dict:
    """Build factor panel data for a single alpha stock."""
    normalized_alpha_scope = normalize_alpha_scope(alpha_scope)
    selected = None
    payload: dict | None = None
    if scores is not None:
        score_items = list(scores)
    else:
        loader = stock_scores_loader or _get_alpha_stock_scores_payload
        payload = loader(
            top_n=max(top_n, 10),
            user=user,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            alpha_scope=normalized_alpha_scope,
        )
        score_items = payload["items"]
    for item in score_items:
        if item.get("code") == stock_code:
            selected = item
            break

    provider = source or (selected.get("source") if selected else "unknown")
    factors = dict(selected.get("factors") or {}) if selected else {}
    factor_origin = "score_payload" if factors else ""
    empty_reason = ""

    if load_provider_factors and not factors and provider in {"simple", "qlib", "etf"}:
        factors = dashboard_interface_services.load_alpha_factor_exposure(
            stock_code,
            provider,
            as_of_date=django_timezone.localdate(),
        )
        if factors:
            factor_origin = f"{provider}_provider"

    if not factors:
        if provider == "qlib":
            empty_reason = "当前 Qlib 流程可展示评分与 IC/ICIR，但尚未输出可视化用的单股因子暴露。"
        elif provider == "cache":
            empty_reason = "当前缓存记录未包含因子明细，请等待新的带因子评分结果写入缓存。"
        elif provider == "etf":
            empty_reason = "ETF 兜底源只提供成份股替代结果，不提供单股因子暴露。"
        else:
            empty_reason = "当前股票暂无可展示的因子暴露数据。"

    sorted_factors = []
    for key, value in factors.items():
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        sorted_factors.append(
            {
                "name": key,
                "value": numeric_value,
                "abs_value": abs(numeric_value),
                "bar_width": min(abs(numeric_value) * 100, 100),
                "direction": "positive" if numeric_value >= 0 else "negative",
            }
        )
    sorted_factors.sort(key=lambda item: item["abs_value"], reverse=True)

    recommendation_basis = dict((selected or {}).get("recommendation_basis") or {})
    alpha_meta = dict(payload["meta"]) if payload else {}
    alpha_pool = dict(payload["pool"]) if payload else {}
    if not alpha_meta and selected:
        alpha_meta = {
            "alpha_scope": normalized_alpha_scope,
            "readiness_status": recommendation_basis.get("freshness_status") or "",
            "scope_verification_status": recommendation_basis.get("scope_verification_status")
            or "",
            "blocked_reason": recommendation_basis.get("blocked_reason")
            or selected.get("blocked_reason")
            or "",
            "must_not_use_for_decision": selected.get("must_not_use_for_decision", True),
        }

    return {
        "stock": selected,
        "stock_code": stock_code,
        "provider": provider,
        "alpha_scope": normalized_alpha_scope,
        "alpha_meta": alpha_meta,
        "alpha_pool": alpha_pool,
        "recommendation_basis": recommendation_basis,
        "factor_basis": recommendation_basis.get("factor_basis") or [],
        "buy_reasons": (selected or {}).get("buy_reasons") or [],
        "no_buy_reasons": (selected or {}).get("no_buy_reasons") or [],
        "risk_snapshot": (selected or {}).get("risk_snapshot") or {},
        "factor_origin": factor_origin,
        "factors": sorted_factors,
        "factor_count": len(sorted_factors),
        "empty_reason": empty_reason,
    }


def _build_alpha_exit_detail_panel_context(
    *,
    exit_watchlist: list[dict[str, object]],
    account_id: int | None = None,
    asset_code: str | None = None,
) -> dict[str, object]:
    """Build sidebar detail context for one exit-watchlist item."""

    normalized_code = str(asset_code or "").strip().upper()
    selected = None
    for item in exit_watchlist:
        item_account_id = item.get("account_id")
        item_code = str(item.get("asset_code") or "").strip().upper()
        if normalized_code and item_code != normalized_code:
            continue
        if account_id is not None and item_account_id not in {account_id, str(account_id)}:
            continue
        selected = item
        break

    if selected is None and exit_watchlist:
        selected = exit_watchlist[0]

    if selected is None:
        return {
            "selected": None,
            "recommendation": {},
            "transition_plan": {},
            "signal_contract": {},
            "has_exit_watchlist": False,
            "empty_reason": "当前没有持仓退出监控项，侧边详情面板会在出现 SELL / REDUCE / 证伪跟踪后展示。",
        }

    return {
        "selected": selected,
        "recommendation": dict(selected.get("recommendation_snapshot") or {}),
        "transition_plan": dict(selected.get("transition_plan_snapshot") or {}),
        "signal_contract": dict(selected.get("signal_contract_snapshot") or {}),
        "has_exit_watchlist": True,
        "empty_reason": "",
    }


def _mark_alpha_exit_watchlist_selection(
    exit_watchlist: list[dict[str, object]],
    *,
    account_id: int | None = None,
    asset_code: str | None = None,
) -> list[dict[str, object]]:
    """Annotate one exit-watchlist item as selected for cross-page deep links."""

    normalized_code = str(asset_code or "").strip().upper()
    selected_index: int | None = None
    for index, item in enumerate(exit_watchlist):
        item_account_id = item.get("account_id")
        item_code = str(item.get("asset_code") or "").strip().upper()
        if normalized_code and item_code != normalized_code:
            continue
        if account_id is not None and item_account_id not in {account_id, str(account_id)}:
            continue
        selected_index = index
        break

    if selected_index is None and exit_watchlist:
        selected_index = 0

    annotated_items: list[dict[str, object]] = []
    for index, item in enumerate(exit_watchlist):
        annotated_item = _clone_dashboard_item(item)
        annotated_item["is_selected"] = selected_index is not None and index == selected_index
        annotated_items.append(annotated_item)
    return annotated_items


def _build_dashboard_exit_entry_panel_context(
    exit_watchlist: list[dict[str, object]],
) -> dict[str, object]:
    """Filter homepage exit-entry items after the user has already handled them."""

    visible_items: list[dict[str, object]] = []
    hidden_processed_count = 0

    for item in exit_watchlist:
        recommendation_snapshot = item.get("recommendation_snapshot") or {}
        if not isinstance(recommendation_snapshot, dict):
            recommendation_snapshot = {}

        user_action = str(recommendation_snapshot.get("user_action") or "").strip().upper()
        if user_action in {"ADOPTED", "IGNORED"}:
            hidden_processed_count += 1
            continue
        visible_items.append(item)

    summary = {
        "total": len(visible_items),
        "urgent_count": sum(1 for item in visible_items if int(item.get("priority_rank", 99)) == 0),
        "sell_count": sum(1 for item in visible_items if item.get("exit_action") == "SELL"),
        "reduce_count": sum(1 for item in visible_items if item.get("exit_action") == "REDUCE"),
        "hold_count": sum(1 for item in visible_items if item.get("exit_action") == "HOLD"),
    }

    return {
        "items": visible_items,
        "summary": summary,
        "hidden_processed_count": hidden_processed_count,
    }


def _build_dashboard_exit_detail_url(
    *,
    asset_code: str | None,
    account_id: int | str | None = None,
    alpha_scope: str = ALPHA_SCOPE_PORTFOLIO,
    portfolio_id: int | None = None,
) -> str:
    """Build the canonical deep link from any exit item back to Dashboard detail."""

    params: list[tuple[str, str | int]] = [("alpha_scope", alpha_scope or ALPHA_SCOPE_PORTFOLIO)]
    if portfolio_id is not None:
        params.append(("portfolio_id", portfolio_id))

    normalized_asset_code = str(asset_code or "").strip().upper()
    if normalized_asset_code:
        params.append(("exit_asset_code", normalized_asset_code))

    if account_id not in (None, ""):
        params.append(("exit_account_id", int(account_id)))

    query = urlencode(params, doseq=True)
    return f"{reverse('dashboard:index')}?{query}#{_DASHBOARD_EXIT_DETAIL_ANCHOR}"


def _annotate_decision_workspace_navigation(
    items: list[dict[str, object]],
    *,
    source: str,
    security_code_key: str,
    view_step: int | None = None,
    primary_step: int | None = None,
    account_id_key: str | None = None,
    action_key: str | None = None,
) -> list[dict[str, object]]:
    """Attach canonical Decision Workspace links to dashboard cards and tables."""

    annotated_items: list[dict[str, object]] = []
    primary_step_value = primary_step if primary_step is not None else view_step

    for item in items:
        annotated_item = _clone_dashboard_item(item)
        account_id = annotated_item.get(account_id_key) if account_id_key else None
        action = annotated_item.get(action_key) if action_key else None
        annotated_item["decision_workspace_url"] = _build_decision_workspace_url(
            security_code=str(annotated_item.get(security_code_key) or ""),
            source=source,
            step=view_step,
            account_id=account_id,
            action=str(action or "") if action is not None else None,
        )
        annotated_item["decision_workspace_primary_url"] = _build_decision_workspace_url(
            security_code=str(annotated_item.get(security_code_key) or ""),
            source=source,
            step=primary_step_value,
            account_id=account_id,
            action=str(action or "") if action is not None else None,
        )
        annotated_items.append(annotated_item)

    return annotated_items


def _annotate_alpha_exit_watchlist_navigation(
    exit_watchlist: list[dict[str, object]],
    *,
    alpha_scope: str = ALPHA_SCOPE_PORTFOLIO,
    portfolio_id: int | None = None,
) -> list[dict[str, object]]:
    """Attach shared deep links and normalized user-action metadata to exit items."""

    annotated_items: list[dict[str, object]] = []
    normalized_scope = normalize_alpha_scope(alpha_scope)

    for item in exit_watchlist:
        annotated_item = _clone_dashboard_item(item)
        recommendation_snapshot = annotated_item.get("recommendation_snapshot") or {}
        if not isinstance(recommendation_snapshot, dict):
            recommendation_snapshot = {}

        user_action = _normalize_exit_user_action(recommendation_snapshot.get("user_action"))
        annotated_item["user_action"] = user_action
        annotated_item["user_action_label"] = _build_exit_user_action_label(user_action)
        annotated_item["is_processed"] = user_action in {"ADOPTED", "IGNORED"}
        annotated_item["dashboard_detail_url"] = _build_dashboard_exit_detail_url(
            asset_code=annotated_item.get("asset_code"),
            account_id=annotated_item.get("account_id"),
            alpha_scope=normalized_scope,
            portfolio_id=portfolio_id,
        )
        annotated_items.append(annotated_item)

    return annotated_items
