"""
Dashboard Interface Views

首页仪表盘视图 - 用户投资指挥中心。

重构说明 (2026-03-11):
- 将跨模块数据获取逻辑从 views.py 移至 Query Services
- views.py 调用 Query Services 获取数据
- 隐藏 ORM 实现细节
"""

import logging
from datetime import date
from types import SimpleNamespace

from celery.result import AsyncResult
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone as django_timezone
from apps.alpha.application.ops_locks import (
    ALPHA_REFRESH_LOCK_TTL_SECONDS,
    acquire_dashboard_alpha_refresh_pending_lock,
    build_dashboard_alpha_refresh_lock_key as _shared_build_alpha_refresh_lock_key,
    build_dashboard_alpha_refresh_metadata,
    promote_dashboard_alpha_refresh_task_lock,
    release_dashboard_alpha_refresh_lock,
    resolve_dashboard_alpha_refresh_lock,
)
from apps.alpha.application.pool_resolver import (
    ALPHA_POOL_MODE_PRICE_COVERED,
    PortfolioAlphaPoolResolver,
    get_alpha_pool_mode_choices,
    normalize_alpha_pool_mode,
)
from apps.task_monitor.application.tracking import record_pending_task
from apps.dashboard.application.alpha_homepage import (
    ALPHA_SCOPE_GENERAL,
    ALPHA_SCOPE_PORTFOLIO,
    normalize_alpha_scope,
)
from apps.dashboard.interface import api_v1_views
from apps.dashboard.interface import alpha_history_views
from apps.dashboard.interface import alpha_metrics_views
from apps.dashboard.interface import macro_views
from apps.dashboard.interface import portfolio_views
from apps.dashboard.interface import alpha_stock_views
from apps.dashboard.interface import workflow_views
from apps.dashboard.application.queries import (
    get_alpha_decision_chain_query,
    get_alpha_homepage_query,
    get_alpha_visualization_query,
    get_dashboard_detail_query,
    get_decision_plane_query,
)
from apps.dashboard.application import interface_services as dashboard_interface_services
logger = logging.getLogger(__name__)
_ALPHA_REFRESH_LOCK_TTL_SECONDS = ALPHA_REFRESH_LOCK_TTL_SECONDS


def _get_request_user_id(user) -> int | None:
    """Return a stable numeric user identifier when available."""
    user_id = getattr(user, "id", None)
    if user_id in (None, ""):
        user_id = getattr(user, "pk", None)
    try:
        return int(user_id) if user_id not in (None, "") else None
    except (TypeError, ValueError):
        return None


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


def _build_dashboard_data(user_id: int):
    """Build dashboard DTO for API and page views."""
    return dashboard_interface_services.build_dashboard_data(user_id)


def _load_simulated_positions_fallback(user_id: int, account_id: int | None = None) -> list[dict]:
    """Read holdings directly from the current simulated-account tables.

    Args:
        user_id: The user whose positions to load.
        account_id: Optional account ID to filter positions by a specific account.
    """
    return dashboard_interface_services.load_simulated_positions_fallback(
        user_id=user_id,
        account_id=account_id,
    )


def _get_dashboard_accounts(user):
    """Load all user investment accounts for dashboard cards."""
    return dashboard_interface_services.get_dashboard_accounts(user)


def _ensure_dashboard_positions(data, user_id: int):
    """Backfill positions for page/HTMX rendering when portfolio snapshot is stale."""
    return dashboard_interface_services.ensure_dashboard_positions(data, user_id)


def _get_dashboard_portfolio_options(user_id: int) -> list[dict]:
    """Load dashboard portfolio choices with a database-only fallback."""
    try:
        return dashboard_interface_services.get_portfolio_options(user_id)
    except DatabaseError as exc:
        logger.warning("Failed to get portfolio options: %s", exc)
        return []


def _get_dashboard_valuation_repair_config_summary() -> dict | None:
    """Load valuation-repair config summary through the dashboard application boundary."""
    return dashboard_interface_services.get_valuation_repair_config_summary(use_cache=False)


def _load_phase1_macro_components(
    as_of_date: date | None = None,
    *,
    refresh_if_stale: bool = False,
):
    """Load navigator, pulse, and action recommendation objects for dashboard widgets."""
    components = dashboard_interface_services.load_phase1_macro_components(
        as_of_date=as_of_date,
        refresh_if_stale=refresh_if_stale,
    )
    return components.navigator, components.pulse, components.action


def _score_to_percent(score: float) -> int:
    """Map a pulse score in [-1, 1] to a percentage width in [0, 100]."""
    bounded = max(-1.0, min(1.0, score))
    return int(round((bounded + 1.0) * 50))


def _parse_positive_int_param(
    raw_value,
    *,
    field_name: str,
    default: int | None = None,
) -> int | None:
    """Parse optional positive-int query params used by HTMX/API endpoints."""
    if raw_value in (None, ""):
        return default

    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc

    if value <= 0:
        raise ValueError(f"{field_name} 必须大于 0")

    return value


def _normalize_dashboard_alpha_pool_mode(raw_value: str | None) -> str:
    """Dashboard defaults to a usable price-covered account pool."""

    return normalize_alpha_pool_mode(raw_value or ALPHA_POOL_MODE_PRICE_COVERED)


def _build_regime_status_context(navigator, pulse, action) -> dict:
    """Build template context for the regime status bar widget."""
    movement = getattr(navigator, "movement", None)
    asset_guidance = getattr(navigator, "asset_guidance", None)
    risk_budget_pct = 0.0

    if action and not getattr(action, "must_not_use_for_decision", False):
        risk_budget_pct = action.risk_budget_pct * 100
    elif asset_guidance:
        risk_budget_pct = asset_guidance.risk_budget_pct * 100

    return {
        "regime_name": navigator.regime_name if navigator else "Unknown",
        "is_transitioning": bool(navigator and navigator.is_transitioning),
        "transition_target": movement.transition_target if movement else None,
        "confidence_pct": (navigator.confidence * 100) if navigator else 0.0,
        "pulse_strength": getattr(pulse, "regime_strength", "moderate"),
        "risk_budget_pct": risk_budget_pct,
        "transition_warning": bool(pulse and pulse.transition_warning),
        "action_blocked": bool(action and getattr(action, "must_not_use_for_decision", False)),
    }


def _build_pulse_card_context(pulse) -> dict:
    """Build template context for the Pulse dashboard widget."""
    dimensions = {ds.dimension: ds for ds in getattr(pulse, "dimension_scores", [])}

    def _dim_value(name: str, field: str, default):
        entry = dimensions.get(name)
        return getattr(entry, field, default) if entry else default

    return {
        "pulse_observed_at": pulse.observed_at.isoformat() if pulse else "",
        "pulse_composite": getattr(pulse, "composite_score", 0.0),
        "pulse_strength": getattr(pulse, "regime_strength", "moderate"),
        "growth_score": _dim_value("growth", "score", 0.0),
        "growth_signal": _dim_value("growth", "signal", "neutral"),
        "growth_pct": _score_to_percent(_dim_value("growth", "score", 0.0)),
        "inflation_score": _dim_value("inflation", "score", 0.0),
        "inflation_signal": _dim_value("inflation", "signal", "neutral"),
        "inflation_pct": _score_to_percent(_dim_value("inflation", "score", 0.0)),
        "liquidity_score": _dim_value("liquidity", "score", 0.0),
        "liquidity_signal": _dim_value("liquidity", "signal", "neutral"),
        "liquidity_pct": _score_to_percent(_dim_value("liquidity", "score", 0.0)),
        "sentiment_score": _dim_value("sentiment", "score", 0.0),
        "sentiment_signal": _dim_value("sentiment", "signal", "neutral"),
        "sentiment_pct": _score_to_percent(_dim_value("sentiment", "score", 0.0)),
        "pulse_transition_warning": bool(pulse and pulse.transition_warning),
        "pulse_transition_direction": getattr(pulse, "transition_direction", None),
        "pulse_transition_reasons": getattr(pulse, "transition_reasons", []),
        "pulse_is_reliable": bool(pulse and pulse.is_reliable),
        "pulse_stale_count": getattr(pulse, "stale_indicator_count", 0),
    }


def _build_action_recommendation_context(action) -> dict:
    """Build template context for the action recommendation widget."""
    if not action:
        return {
            "action_weights": {},
            "action_risk_budget": 0.0,
            "action_position_limit": 0.0,
            "action_sectors": [],
            "action_styles": [],
            "action_hedge": None,
            "action_regime_contribution": "",
            "action_pulse_contribution": "",
            "action_reasoning": "当前暂无联合行动建议，请先完成 Regime 与 Pulse 数据计算。",
            "action_confidence": 0.0,
            "action_blocked": False,
            "action_blocked_reason": "",
            "action_blocked_code": "",
            "action_stale_indicator_codes": [],
        }

    is_blocked = bool(getattr(action, "must_not_use_for_decision", False))
    return {
        "action_weights": {
            category: weight * 100 for category, weight in action.asset_weights.items()
        },
        "action_risk_budget": action.risk_budget_pct * 100,
        "action_position_limit": action.position_limit_pct * 100,
        "action_sectors": action.recommended_sectors,
        "action_styles": action.benefiting_styles,
        "action_hedge": action.hedge_recommendation,
        "action_regime_contribution": action.regime_contribution,
        "action_pulse_contribution": action.pulse_contribution,
        "action_reasoning": action.reasoning,
        "action_confidence": action.confidence * 100,
        "action_blocked": is_blocked,
        "action_blocked_reason": getattr(action, "blocked_reason", ""),
        "action_blocked_code": getattr(action, "blocked_code", ""),
        "action_stale_indicator_codes": list(getattr(action, "stale_indicator_codes", []) or []),
    }


def _build_attention_items_context(data, navigator, pulse) -> dict:
    """Build template context for the dashboard attention widget."""
    items: list[dict[str, str]] = []
    active_signals = list(getattr(data, "active_signals", []) or [])

    if active_signals:
        first_signal = active_signals[0]
        items.append(
            {
                "level": "high",
                "title": f"{len(active_signals)} 条信号待跟进",
                "detail": (
                    f"优先处理 {first_signal.get('asset_code', '未知标的')}"
                    " 的已批准信号。"
                ),
                "meta": "来源: signal",
            }
        )

    if pulse and pulse.transition_warning:
        reasons = "；".join(pulse.transition_reasons[:2]) or "多维脉搏与当前 Regime 产生冲突。"
        items.append(
            {
                "level": "medium",
                "title": f"Pulse 转向 {pulse.transition_direction or '待确认'} 预警",
                "detail": reasons,
                "meta": "来源: pulse",
            }
        )
    elif navigator and navigator.is_transitioning:
        items.append(
            {
                "level": "medium",
                "title": f"Regime 可能转向 {navigator.movement.transition_target or '新象限'}",
                "detail": navigator.movement.momentum_summary,
                "meta": "来源: regime",
            }
        )

    if getattr(data, "position_count", 0) == 0:
        items.append(
            {
                "level": "low",
                "title": "当前无持仓",
                "detail": "可以直接进入新决策 Workflow，按 6-step funnel 完成配置决策。",
                "meta": "来源: account",
            }
        )

    if not items:
        items.append(
            {
                "level": "low",
                "title": "当前无紧急待办",
                "detail": "Regime、Pulse 与持仓状态稳定，可按计划例行复核。",
                "meta": "来源: dashboard",
            }
        )

    return {
        "attention_items": items[:4],
        "attention_count": len(items[:4]),
    }


def _build_browser_notification_context(navigator, pulse) -> dict:
    """Build optional browser-notification payload for dashboard alerts."""
    payload: dict[str, str] | None = None

    if pulse and pulse.transition_warning:
        reasons = "；".join((pulse.transition_reasons or [])[:2]) or "多维脉搏与当前 Regime 产生冲突。"
        payload = {
            "title": f"Pulse 转向 {pulse.transition_direction or '待确认'} 预警",
            "body": reasons,
            "tag": f"pulse-{pulse.observed_at.isoformat()}-{pulse.transition_direction or 'warning'}",
        }
    elif navigator and navigator.is_transitioning:
        payload = {
            "title": f"Regime 可能转向 {navigator.movement.transition_target or '新象限'}",
            "body": navigator.movement.momentum_summary,
            "tag": f"regime-{navigator.generated_at.isoformat()}-{navigator.movement.transition_target or 'warning'}",
        }

    return {
        "browser_notification_enabled": True,
        "browser_notification_payload": payload,
    }


# ========================================
# Alpha 可视化数据获取函数（委托至 Query Services）
# ========================================

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
) -> dict:
    """Build factor panel data for a single alpha stock."""
    normalized_alpha_scope = normalize_alpha_scope(alpha_scope)
    selected = None
    payload: dict | None = None
    if scores is not None:
        score_items = list(scores)
    else:
        payload = _get_alpha_stock_scores_payload(
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
            "scope_verification_status": recommendation_basis.get("scope_verification_status") or "",
            "blocked_reason": recommendation_basis.get("blocked_reason") or selected.get("blocked_reason") or "",
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
        annotated_item = dict(item)
        annotated_item["is_selected"] = selected_index is not None and index == selected_index
        annotated_items.append(annotated_item)
    return annotated_items


@login_required(login_url="/account/login/")
def dashboard_entry(request):
    """
    Dashboard entrypoint.

    If Streamlit dashboard is enabled, redirect to Streamlit URL.
    Otherwise fall back to legacy Django dashboard page.
    """
    if settings.STREAMLIT_DASHBOARD_ENABLED:
        return redirect(settings.STREAMLIT_DASHBOARD_URL)
    return dashboard_view(request)


@login_required(login_url="/account/login/")
def dashboard_view(request):
    """
    首页仪表盘视图

    展示：
    1. 宏观环境快照（当前Regime）
    2. 我的资产总览
    3. 当前持仓列表
    4. 我的投资信号
    5. AI操作建议
    """
    # 获取首页数据
    data = _build_dashboard_data(request.user.id)
    data = _ensure_dashboard_positions(data, request.user.id)
    navigator, pulse, action = _load_phase1_macro_components()

    # 补充用户名
    data.username = request.user.username
    selected_portfolio_id = request.GET.get("portfolio_id")
    if selected_portfolio_id not in (None, ""):
        try:
            selected_portfolio_id = _parse_positive_int_param(
                selected_portfolio_id,
                field_name="portfolio_id",
                default=0,
            )
        except ValueError:
            selected_portfolio_id = None
    else:
        selected_portfolio_id = None
    selected_alpha_pool_mode = _normalize_dashboard_alpha_pool_mode(request.GET.get("pool_mode"))
    portfolio_options = _get_dashboard_portfolio_options(request.user.id)
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
    if requested_alpha_scope in (None, "") and not portfolio_options and selected_portfolio_id is None:
        selected_alpha_scope = ALPHA_SCOPE_GENERAL

    decision_plane_data = _get_decision_plane_data(max_candidates=5, max_pending=10)

    alpha_metrics_data = _get_alpha_metrics_data(ic_days=30)

    alpha_payload = _get_alpha_stock_scores_payload(
        top_n=10,
        user=request.user,
        portfolio_id=selected_portfolio_id,
        pool_mode=selected_alpha_pool_mode,
        alpha_scope=selected_alpha_scope,
    )
    alpha_actionable_candidates = alpha_payload["actionable_candidates"]
    alpha_pending_requests = alpha_payload["pending_requests"]
    alpha_stock_scores = alpha_payload["items"]
    alpha_decision_chain_overview = _build_alpha_decision_chain_overview(
        top_candidates=alpha_stock_scores,
        actionable_candidates=alpha_actionable_candidates,
        pending_requests=alpha_pending_requests,
    )
    investment_accounts = _get_dashboard_accounts(request.user)
    valuation_repair_config_summary = _get_dashboard_valuation_repair_config_summary()

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
        alpha_payload=alpha_payload,
        alpha_decision_chain_overview=alpha_decision_chain_overview,
        valuation_repair_config_summary=valuation_repair_config_summary,
        selected_exit_asset_code=selected_exit_asset_code,
        selected_exit_account_id=selected_exit_account_id,
    )

    return render(request, 'dashboard/index.html', context)


def _build_dashboard_page_context(
    *,
    request,
    data,
    navigator,
    pulse,
    action,
    portfolio_options: list[dict],
    investment_accounts: list[dict],
    selected_portfolio_id: int | None,
    selected_alpha_pool_mode: str,
    selected_alpha_scope: str,
    decision_plane_data,
    alpha_metrics_data,
    alpha_payload: dict,
    alpha_decision_chain_overview: dict,
    valuation_repair_config_summary: dict | None,
    selected_exit_asset_code: str | None,
    selected_exit_account_id: int | None,
) -> dict:
    """Build the dashboard template context from already-loaded read models."""
    alpha_stock_scores = alpha_payload["items"]
    alpha_stock_scores_meta = alpha_payload["meta"]
    alpha_actionable_candidates = alpha_payload["actionable_candidates"]
    alpha_exit_watchlist = _mark_alpha_exit_watchlist_selection(
        alpha_payload.get("exit_watchlist", []),
        account_id=selected_exit_account_id,
        asset_code=selected_exit_asset_code,
    )
    alpha_exit_watch_summary = alpha_payload.get("exit_watch_summary", {})
    alpha_exit_detail_panel = _build_alpha_exit_detail_panel_context(
        exit_watchlist=alpha_exit_watchlist,
        account_id=selected_exit_account_id,
        asset_code=selected_exit_asset_code,
    )
    alpha_pending_requests = alpha_payload["pending_requests"]
    workflow_actionable_candidates = decision_plane_data.actionable_candidates
    workflow_pending_requests = decision_plane_data.pending_requests
    initial_alpha_stock = alpha_stock_scores[0]["code"] if alpha_stock_scores else ""

    context = {
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
        "allocation_data": data.allocation_data if hasattr(data, 'allocation_data') else {},
        "performance_data": data.performance_data if hasattr(data, 'performance_data') else [],
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
        "alpha_stock_scores_meta": alpha_stock_scores_meta,
        "alpha_actionable_candidates": alpha_actionable_candidates,
        "alpha_exit_watchlist": alpha_exit_watchlist,
        "alpha_exit_watch_summary": alpha_exit_watch_summary,
        "alpha_exit_detail_panel": alpha_exit_detail_panel,
        "alpha_exit_selected_asset_code": alpha_exit_detail_panel.get("selected", {}).get("asset_code")
        if alpha_exit_detail_panel.get("selected")
        else "",
        "alpha_exit_selected_account_id": alpha_exit_detail_panel.get("selected", {}).get("account_id")
        if alpha_exit_detail_panel.get("selected")
        else "",
        "alpha_pending_requests": alpha_pending_requests,
        "alpha_pool": alpha_payload["pool"],
        "alpha_recent_runs": alpha_payload["recent_runs"],
        "alpha_history_run_id": alpha_payload["history_run_id"],
        "selected_portfolio_id": selected_portfolio_id or alpha_payload["pool"].get("portfolio_id"),
        "selected_alpha_pool_mode": selected_alpha_pool_mode or alpha_payload["pool"].get("pool_mode"),
        "selected_alpha_scope": selected_alpha_scope,
        "alpha_pool_mode_choices": get_alpha_pool_mode_choices(),
        "alpha_provider_status": alpha_metrics_data.provider_status,
        "alpha_coverage_metrics": alpha_metrics_data.coverage_metrics,
        "alpha_ic_trends": alpha_metrics_data.ic_trends,
        "alpha_factor_panel": _build_alpha_factor_panel(
            initial_alpha_stock,
            top_n=10,
            scores=alpha_stock_scores,
            user=request.user,
            portfolio_id=selected_portfolio_id or alpha_payload["pool"].get("portfolio_id"),
            pool_mode=selected_alpha_pool_mode,
            alpha_scope=selected_alpha_scope,
            load_provider_factors=False,
        ),
        "valuation_repair_config_summary": valuation_repair_config_summary,
    }
    context.update(_build_regime_status_context(navigator, pulse, action))
    context.update(_build_pulse_card_context(pulse))
    context.update(_build_action_recommendation_context(action))
    context.update(_build_attention_items_context(data, navigator, pulse))
    context.update(_build_browser_notification_context(navigator, pulse))
    return context


# ========================================
# 决策平面数据获取辅助函数（委托至 Query Services）
# ========================================


def _empty_decision_plane_data() -> SimpleNamespace:
    """Return a safe fallback when decision-plane aggregation is unavailable."""
    return SimpleNamespace(
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


def _get_actionable_candidates():
    """
    首页主流程展示：可操作候选列表（含估值修复信息）

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data(max_candidates=5, max_pending=10).actionable_candidates


def _get_pending_requests():
    """
    首页主流程展示：已批准但未执行/失败待重试请求

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    return _get_decision_plane_data(max_candidates=5, max_pending=10).pending_requests


def _get_pending_count() -> int:
    return len(_get_pending_requests())


def _get_decision_plane_data(max_candidates: int = 5, max_pending: int = 10):
    """Return the aggregated decision-plane payload with a single query execution."""
    data = dashboard_interface_services.get_decision_plane_data(
        max_candidates=max_candidates,
        max_pending=max_pending,
        query_factory=get_decision_plane_query,
    )
    return data or _empty_decision_plane_data()


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
