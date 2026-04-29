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
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone as django_timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.account.interface.authentication import MultiTokenAuthentication
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
from apps.dashboard.application.alpha_homepage import (
    ALPHA_SCOPE_GENERAL,
    ALPHA_SCOPE_PORTFOLIO,
    normalize_alpha_scope,
)
from apps.dashboard.application.queries import (
    get_alpha_decision_chain_query,
    get_alpha_homepage_query,
    get_alpha_visualization_query,
    get_dashboard_detail_query,
    get_decision_plane_query,
)
from apps.dashboard.application import interface_services as dashboard_interface_services
from core.cache_utils import CACHE_TTL, cached_api

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
    try:
        from apps.task_monitor.application.repository_provider import get_celery_health_checker

        health = get_celery_health_checker().check_health()
        active_workers = list(getattr(health, "active_workers", []) or [])
        if active_workers and bool(getattr(health, "is_healthy", False)):
            return {"available": True, "active_workers": active_workers, "reason": "healthy"}
        if not active_workers:
            return {"available": False, "active_workers": [], "reason": "no_active_workers"}
        return {"available": False, "active_workers": active_workers, "reason": "unhealthy"}
    except Exception as exc:
        logger.warning("Failed to inspect Celery health for dashboard alpha refresh: %s", exc)
        return {
            "available": False,
            "active_workers": [],
            "reason": "health_check_failed",
            "error": str(exc),
        }


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


def _load_phase1_macro_components(
    as_of_date: date | None = None,
    *,
    refresh_if_stale: bool = False,
):
    """Load navigator, pulse, and action recommendation objects for dashboard widgets."""
    target_date = as_of_date or date.today()
    navigator = None
    pulse = None
    action = None

    try:
        from apps.regime.application.navigator_use_cases import BuildRegimeNavigatorUseCase

        navigator = BuildRegimeNavigatorUseCase().execute(target_date)
    except Exception as exc:
        logger.warning("Failed to load regime navigator widget data: %s", exc)

    try:
        from apps.pulse.application.use_cases import GetLatestPulseUseCase

        pulse = GetLatestPulseUseCase().execute(
            as_of_date=target_date,
            refresh_if_stale=refresh_if_stale,
        )
    except Exception as exc:
        logger.warning("Failed to load pulse widget data: %s", exc)

    try:
        from apps.regime.application.navigator_use_cases import GetActionRecommendationUseCase

        action = GetActionRecommendationUseCase().execute(
            target_date,
            refresh_pulse_if_stale=refresh_if_stale,
        )
    except Exception as exc:
        logger.warning("Failed to load action recommendation widget data: %s", exc)

    return navigator, pulse, action


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
    try:
        query = get_alpha_homepage_query()
        data = query.execute(
            top_n=top_n,
            user=user,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            alpha_scope=normalized_alpha_scope,
        )
        meta = dict(data.meta)
        meta.setdefault("alpha_scope", normalized_alpha_scope)
        pool = dict(data.pool)
        pool.setdefault("alpha_scope", normalized_alpha_scope)
        return {
            "items": data.top_candidates,
            "meta": meta,
            "pool": pool,
            "actionable_candidates": data.actionable_candidates,
            "pending_requests": data.pending_requests,
            "recent_runs": data.recent_runs,
            "history_run_id": data.history_run_id,
        }
    except Exception as e:
        logger.warning(f"Failed to get alpha stock scores payload: {e}")
        return {
            "items": [],
            "meta": {
                "status": "error",
                "source": "none",
                "warning_message": "alpha_stock_scores_unavailable",
                "is_degraded": True,
                "uses_cached_data": False,
                "alpha_scope": normalized_alpha_scope,
                "recommendation_ready": False,
                "must_not_use_for_decision": True,
            },
            "pool": {"alpha_scope": normalized_alpha_scope},
            "actionable_candidates": [],
            "pending_requests": [],
            "recent_runs": [],
            "history_run_id": None,
        }


def _get_alpha_visualization_data(top_n: int = 10, ic_days: int = 30, user=None):
    """Return the aggregated Alpha visualization payload with a single query execution."""
    try:
        query = get_alpha_visualization_query()
        return query.execute(top_n=top_n, ic_days=ic_days, user=user)
    except Exception as e:
        logger.warning(f"Failed to get alpha visualization data: {e}")
        return None


def _get_empty_alpha_metrics_data():
    """Return empty Alpha metrics for degraded dashboard rendering."""
    return SimpleNamespace(
        stock_scores=[],
        stock_scores_meta={},
        provider_status={
            "providers": {},
            "metrics": {},
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "provider_status_unavailable",
        },
        coverage_metrics={
            "coverage_ratio": 0.0,
            "total_requests": 0,
            "cache_hit_rate": 0.0,
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "coverage_metrics_unavailable",
        },
        ic_trends=[],
        ic_trends_meta={
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        },
    )


def _get_alpha_metrics_data(ic_days: int = 30):
    """Return Alpha dashboard metrics without reloading stock recommendations."""
    try:
        query = get_alpha_visualization_query()
        if hasattr(query, "execute_metrics"):
            return query.execute_metrics(ic_days=ic_days)
        return query.execute(top_n=0, ic_days=ic_days, user=None)
    except Exception as e:
        logger.warning(f"Failed to get alpha metrics data: {e}")
        return _get_empty_alpha_metrics_data()


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
    try:
        data = _get_alpha_metrics_data(ic_days=30)
        return data.provider_status
    except Exception as e:
        logger.warning(f"Failed to get alpha provider status: {e}")
        return {
            "providers": {},
            "metrics": {},
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "provider_status_unavailable",
        }


def _get_alpha_coverage_metrics(user=None) -> dict:
    """
    获取 Alpha 覆盖率指标

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    try:
        data = _get_alpha_metrics_data(ic_days=30)
        return data.coverage_metrics
    except Exception as e:
        logger.warning(f"Failed to get alpha coverage metrics: {e}")
        return {
            "coverage_ratio": 0.0,
            "total_requests": 0,
            "cache_hit_rate": 0.0,
            "timestamp": None,
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "coverage_metrics_unavailable",
        }


def _get_alpha_ic_trends_payload(days: int = 30, user=None) -> dict:
    """
    获取 Alpha IC/ICIR 趋势数据

    重构说明 (2026-03-11):
    - 委托至 AlphaVisualizationQuery
    """
    try:
        data = _get_alpha_metrics_data(ic_days=days)
        return {
            "items": data.ic_trends,
            "status": data.ic_trends_meta.get("status", "available"),
            "data_source": data.ic_trends_meta.get("data_source", "live"),
            "warning_message": data.ic_trends_meta.get("warning_message"),
        }
    except Exception as e:
        logger.warning(f"Failed to get alpha IC trends: {e}")
        return {
            "items": [],
            "status": "degraded",
            "data_source": "fallback",
            "warning_message": "ic_trends_unavailable",
        }


def _get_alpha_ic_trends(days: int = 30, user=None) -> list:
    return _get_alpha_ic_trends_payload(days, user=user)["items"]


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
    try:
        query = get_alpha_decision_chain_query()
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
    except Exception as e:
        logger.warning(f"Failed to get alpha decision chain data: {e}")
        return None


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
        try:
            from apps.alpha.application.services import AlphaService

            service = AlphaService()
            provider_instance = service._registry.get_provider(provider)
            if provider_instance:
                factors = provider_instance.get_factor_exposure(stock_code, django_timezone.localdate()) or {}
                if factors:
                    factor_origin = f"{provider}_provider"
        except Exception as exc:
            logger.warning("Failed to load factor exposure for %s: %s", stock_code, exc)

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
    try:
        portfolio_options = dashboard_interface_services.get_portfolio_options(request.user.id)
    except Exception as e:
        logger.warning(f"Failed to get portfolio options: {e}")
        portfolio_options = []
    requested_alpha_scope = request.GET.get("alpha_scope")
    selected_alpha_scope = normalize_alpha_scope(requested_alpha_scope)
    if requested_alpha_scope in (None, "") and not portfolio_options and selected_portfolio_id is None:
        selected_alpha_scope = ALPHA_SCOPE_GENERAL

    decision_plane_data = _get_decision_plane_data(max_candidates=5, max_pending=10)
    if decision_plane_data is None:
        decision_plane_data = SimpleNamespace(
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

    alpha_metrics_data = _get_alpha_metrics_data(ic_days=30)

    alpha_payload = _get_alpha_stock_scores_payload(
        top_n=10,
        user=request.user,
        portfolio_id=selected_portfolio_id,
        pool_mode=selected_alpha_pool_mode,
        alpha_scope=selected_alpha_scope,
    )
    workflow_actionable_candidates = decision_plane_data.actionable_candidates
    workflow_pending_requests = decision_plane_data.pending_requests
    alpha_actionable_candidates = alpha_payload["actionable_candidates"]
    alpha_pending_requests = alpha_payload["pending_requests"]
    alpha_stock_scores = alpha_payload["items"]
    alpha_stock_scores_meta = alpha_payload["meta"]
    alpha_decision_chain_overview = _build_alpha_decision_chain_overview(
        top_candidates=alpha_stock_scores,
        actionable_candidates=alpha_actionable_candidates,
        pending_requests=alpha_pending_requests,
    )
    initial_alpha_stock = alpha_stock_scores[0]["code"] if alpha_stock_scores else ""
    investment_accounts = _get_dashboard_accounts(request.user)
    try:
        from apps.equity.application.config import get_valuation_repair_config_summary
        valuation_repair_config_summary = get_valuation_repair_config_summary(use_cache=False)
    except Exception as e:
        logger.warning(f"Failed to get valuation repair config summary: {e}")
        valuation_repair_config_summary = None

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

    return render(request, 'dashboard/index.html', context)


# ========================================
# HTMX 专用视图
# ========================================


@login_required(login_url="/account/login/")
def regime_status_htmx(request):
    """Render the regime status bar partial for HTMX refreshes."""
    navigator, pulse, action = _load_phase1_macro_components()
    context = _build_regime_status_context(navigator, pulse, action)
    return render(request, "components/regime_status_bar.html", context)


@login_required(login_url="/account/login/")
def pulse_card_htmx(request):
    """Render the Pulse card partial for HTMX refreshes."""
    _, pulse, _ = _load_phase1_macro_components()
    context = _build_pulse_card_context(pulse)
    return render(request, "components/pulse_card.html", context)


@login_required(login_url="/account/login/")
def action_recommendation_htmx(request):
    """Render the action recommendation partial for HTMX refreshes."""
    _, _, action = _load_phase1_macro_components()
    context = _build_action_recommendation_context(action)
    return render(request, "components/action_recommendation.html", context)


@login_required(login_url="/account/login/")
def attention_items_htmx(request):
    """Render today's attention-items partial for HTMX refreshes."""
    data = _ensure_dashboard_positions(_build_dashboard_data(request.user.id), request.user.id)
    navigator, pulse, _ = _load_phase1_macro_components()
    context = _build_attention_items_context(data, navigator, pulse)
    return render(request, "components/attention_items.html", context)


@login_required(login_url="/account/login/")
def position_detail_htmx(request, asset_code: str):
    """
    HTMX 持仓详情视图

    用于在模态框中显示持仓详情，包括：
    - 持仓基本信息
    - 历史价格走势
    - 相关投资信号
    """
    context = get_dashboard_detail_query().get_position_detail(
        user_id=request.user.id,
        asset_code=asset_code,
    )

    return render(request, 'dashboard/partials/position_detail.html', context)


@login_required(login_url="/account/login/")
def positions_list_htmx(request):
    """
    HTMX 持仓列表视图

    支持排序、筛选和按账户过滤的持仓列表，用于动态更新。
    """
    # If not accessed via HTMX, redirect to main dashboard
    if 'HX-Request' not in request.headers:
        from django.shortcuts import redirect
        return redirect('dashboard:index')

    # 账户过滤
    try:
        account_id = _parse_positive_int_param(
            request.GET.get('account_id', ''),
            field_name='account_id',
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    # 直接从模拟账户加载持仓（避免构建完整 Dashboard 数据）
    positions = _load_simulated_positions_fallback(request.user.id, account_id=account_id)

    # 若无模拟持仓且未指定账户，回退到组合快照
    if not positions and not account_id:
        data = _build_dashboard_data(request.user.id)
        data = _ensure_dashboard_positions(data, request.user.id)
        positions = list(data.positions)

    # 获取排序参数
    sort_by = request.GET.get('sort', 'market_value')

    # 排序
    if sort_by == 'code':
        positions.sort(key=lambda p: p.get("asset_code", "") if isinstance(p, dict) else p.asset_code)
    elif sort_by == 'pnl_pct':
        positions.sort(
            key=lambda p: p.get("unrealized_pnl_pct", 0) if isinstance(p, dict) else (p.unrealized_pnl_pct or 0),
            reverse=True,
        )
    elif sort_by == 'market_value':
        positions.sort(
            key=lambda p: p.get("market_value", 0) if isinstance(p, dict) else (p.market_value or 0),
            reverse=True,
        )

    context = {
        'positions': positions,
        'show_account': not account_id,
    }

    return render(request, 'dashboard/partials/positions_table.html', context)


def _generate_allocation_from_positions(positions: list[dict]) -> dict:
    """Generate allocation chart data from position dicts, grouped by asset class."""
    allocation: dict[str, float] = {}
    for pos in positions:
        asset_class = pos.get("asset_class_display") or pos.get("asset_class", "其他")
        allocation[asset_class] = allocation.get(asset_class, 0) + pos.get("market_value", 0)
    return allocation


@login_required(login_url="/account/login/")
def allocation_chart_htmx(request):
    """
    HTMX 资产配置图表数据

    返回 JSON 格式的资产配置数据，用于前端图表更新。
    支持 account_id 参数按账户过滤，不传则返回全部账户汇总。
    """
    try:
        account_id = _parse_positive_int_param(
            request.GET.get('account_id', ''),
            field_name='account_id',
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    positions = _load_simulated_positions_fallback(request.user.id, account_id=account_id)
    allocation_data = _generate_allocation_from_positions(positions)

    return JsonResponse({
        'success': True,
        'data': allocation_data
    })


@login_required(login_url="/account/login/")
def performance_chart_htmx(request):
    """
    HTMX 收益趋势图表数据

    返回 JSON 格式的收益历史数据。
    支持 account_id 参数按账户过滤。
    """
    try:
        account_id = _parse_positive_int_param(
            request.GET.get('account_id', ''),
            field_name='account_id',
            default=None,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    performance_data = dashboard_interface_services.build_performance_chart_data(
        user_id=request.user.id,
        account_id=account_id,
    )

    return JsonResponse({
        'success': True,
        'data': performance_data
    })


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='dashboard_summary', ttl_seconds=CACHE_TTL['dashboard_summary'], include_user=True)
def dashboard_summary_v1(request):
    """Summary endpoint for Streamlit dashboard."""
    data = _build_dashboard_data(request.user.id)
    return Response(
        {
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "display_name": data.display_name,
            },
            "regime": {
                "current": data.current_regime,
                "confidence": data.regime_confidence,
                "date": data.regime_date.isoformat() if data.regime_date else None,
            },
            "portfolio": {
                "total_assets": data.total_assets,
                "initial_capital": data.initial_capital,
                "total_return": data.total_return,
                "total_return_pct": data.total_return_pct,
                "cash_balance": data.cash_balance,
                "invested_value": data.invested_value,
                "invested_ratio": data.invested_ratio,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='regime_quadrant', ttl_seconds=CACHE_TTL['regime_current'], include_user=False)
def regime_quadrant_v1(request):
    """Regime quadrant data for Streamlit visualization."""
    data = _build_dashboard_data(request.user.id)
    return Response(
        {
            "current_regime": data.current_regime,
            "distribution": data.regime_distribution or {},
            "confidence": data.regime_confidence,
            "as_of_date": data.regime_date.isoformat() if data.regime_date else None,
            "macro": {
                "pmi": data.pmi_value,
                "cpi": data.cpi_value,
                "growth_momentum_z": data.growth_momentum_z,
                "inflation_momentum_z": data.inflation_momentum_z,
            },
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
def equity_curve_v1(request):
    """
    Equity curve data for Streamlit.
    """
    requested_range = request.GET.get("range", "ALL").upper()
    data = _build_dashboard_data(request.user.id)
    series = data.performance_data if hasattr(data, "performance_data") else []

    if not series:
        # Defensive fallback for first-load or empty-history edge cases.
        series = [
            {
                "date": date.today().isoformat(),
                "portfolio_value": data.total_assets,
                "return_pct": data.total_return_pct,
            }
        ]

    return Response(
        {
            "range": requested_range,
            "has_history": bool(data.performance_data),
            "series": series,
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
@cached_api(key_prefix='signal_status', ttl_seconds=CACHE_TTL['signal_list'], vary_on=['limit'], include_user=True)
def signal_status_v1(request):
    """Signal status and recent signal list for Streamlit."""
    try:
        limit = max(1, min(int(request.GET.get("limit", 50)), 200))
    except ValueError:
        limit = 50

    data = _build_dashboard_data(request.user.id)
    signals = data.active_signals if data.active_signals else []
    return Response(
        {
            "stats": data.signal_stats,
            "signals": signals[:limit],
            "limit": limit,
        }
    )


@api_view(["GET"])
@authentication_classes([SessionAuthentication, MultiTokenAuthentication])
@permission_classes([IsAuthenticated])
def alpha_decision_chain_v1(request):
    """Unified Alpha ranking -> actionable -> pending chain for dashboard/MCP/SDK."""
    try:
        top_n = _parse_positive_int_param(
            request.GET.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        max_candidates = _parse_positive_int_param(
            request.GET.get("max_candidates", 5),
            field_name="max_candidates",
            default=5,
        )
        max_pending = _parse_positive_int_param(
            request.GET.get("max_pending", 10),
            field_name="max_pending",
            default=10,
        )
    except ValueError as exc:
        return Response({"success": False, "error": str(exc)}, status=400)

    chain_data = _get_alpha_decision_chain_data(
        top_n=top_n,
        ic_days=30,
        max_candidates=max_candidates,
        max_pending=max_pending,
        user=request.user,
    )

    if chain_data is None:
        return Response(
            {"success": False, "error": "alpha_decision_chain_unavailable"},
            status=503,
        )

    return Response(
        {
            "success": True,
            "data": {
                "overview": chain_data.overview,
                "top_stocks": chain_data.top_stocks,
                "actionable_candidates": chain_data.actionable_candidates,
                "pending_requests": chain_data.pending_requests,
                "top_n": top_n,
                "max_candidates": max_candidates,
                "max_pending": max_pending,
            },
        }
    )


# ========================================
# 决策平面数据获取辅助函数（委托至 Query Services）
# ========================================

def _get_beta_gate_visible_classes() -> str:
    """
    获取 Beta Gate 允许的可见资产类别

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.beta_gate_visible_classes
    except Exception as e:
        logger.warning(f"Failed to get beta gate visible classes: {e}")
        return "-"


def _get_alpha_status_count(status: str) -> int:
    """
    获取 Alpha 候选状态计数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        if status == "WATCH":
            return data.alpha_watch_count
        elif status == "CANDIDATE":
            return data.alpha_candidate_count
        elif status == "ACTIONABLE":
            return data.alpha_actionable_count
        return 0
    except Exception as e:
        logger.warning(f"Failed to get alpha status count for {status}: {e}")
        return 0


def _get_quota_total() -> int:
    """
    获取决策配额总数

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_total
    except Exception as e:
        logger.warning(f"Failed to get quota total: {e}")
        return 10


def _get_quota_used() -> int:
    """
    获取已使用的决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_used
    except Exception as e:
        logger.warning(f"Failed to get quota used: {e}")
        return 0


def _get_quota_remaining() -> int:
    """
    获取剩余决策配额

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_remaining
    except Exception as e:
        logger.warning(f"Failed to get quota remaining: {e}")
        return 10


def _get_quota_usage_percent() -> float:
    """
    获取决策配额使用百分比

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute()
        return data.quota_usage_percent
    except Exception as e:
        logger.warning(f"Failed to get quota usage percent: {e}")
        return 0.0


def _get_actionable_candidates():
    """
    首页主流程展示：可操作候选列表（含估值修复信息）

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute(max_candidates=5, max_pending=10)
        return data.actionable_candidates
    except Exception as e:
        logger.warning(f"Failed to get actionable candidates: {e}")
        return []


def _get_pending_requests():
    """
    首页主流程展示：已批准但未执行/失败待重试请求

    重构说明 (2026-03-11):
    - 委托至 DecisionPlaneQuery
    """
    try:
        query = get_decision_plane_query()
        data = query.execute(max_candidates=5, max_pending=10)
        return data.pending_requests
    except Exception as e:
        logger.warning(f"Failed to get pending requests: {e}")
        return []


def _get_pending_count() -> int:
    try:
        return len(_get_pending_requests())
    except Exception:
        return 0


def _get_decision_plane_data(max_candidates: int = 5, max_pending: int = 10):
    """Return the aggregated decision-plane payload with a single query execution."""
    try:
        query = get_decision_plane_query()
        return query.execute(max_candidates=max_candidates, max_pending=max_pending)
    except Exception as e:
        logger.warning(f"Failed to get decision plane data: {e}")
        return None


@login_required(login_url="/account/login/")
def workflow_refresh_candidates(request):
    """
    主流程候选刷新：从活跃触发器补齐候选，并尝试提升高置信候选为 ACTIONABLE。
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        result = get_dashboard_detail_query().generate_alpha_candidates()

        return JsonResponse({
            "success": True,
            "result": result,
        })

    except Exception as e:
        logger.error(f"Failed to refresh workflow candidates: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": str(e)}, status=500)


# ========================================
# Alpha 可视化 HTMX 视图
# ========================================

@login_required(login_url="/account/login/")
def alpha_refresh_htmx(request):
    """Trigger a manual realtime Alpha refresh for today's dashboard universe."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        target_date = django_timezone.localdate()
        top_n = _parse_positive_int_param(
            request.POST.get("top_n", 10),
            field_name="top_n",
            default=10,
        )
        raw_portfolio_id = request.POST.get("portfolio_id")
        pool_mode = _normalize_dashboard_alpha_pool_mode(request.POST.get("pool_mode"))
        raw_alpha_scope = request.POST.get("alpha_scope")
        alpha_scope = normalize_alpha_scope(raw_alpha_scope)
        portfolio_id = (
            _parse_positive_int_param(raw_portfolio_id, field_name="portfolio_id", default=0)
            if raw_portfolio_id not in (None, "")
            else None
        )
        if alpha_scope == ALPHA_SCOPE_PORTFOLIO and raw_alpha_scope not in (None, "") and portfolio_id is None:
            raise ValueError("账户专属 Alpha 推理必须提供 portfolio_id")

        user_id = _get_request_user_id(request.user)
        raw_universe_id = str(request.POST.get("universe_id") or "").strip() or "csi300"
        resolved_pool = None
        if alpha_scope == ALPHA_SCOPE_PORTFOLIO and user_id is not None:
            resolved_pool = PortfolioAlphaPoolResolver().resolve(
                user_id=user_id,
                portfolio_id=portfolio_id,
                trade_date=target_date,
                pool_mode=pool_mode,
            )

        use_sync = request.POST.get("sync") in ("1", "true")
        sync_reason = None
        universe_id = resolved_pool.scope.universe_id if resolved_pool is not None else raw_universe_id
        scope_hash = resolved_pool.scope.scope_hash if resolved_pool is not None else None
        lock_meta_payload = build_dashboard_alpha_refresh_metadata(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            universe_id=universe_id,
            portfolio_id=portfolio_id,
            pool_mode=resolved_pool.scope.pool_mode if resolved_pool is not None else pool_mode,
            scope_hash=scope_hash,
        )
        lock_key = _build_alpha_refresh_lock_key(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            raw_universe_id=raw_universe_id,
            resolved_pool=resolved_pool,
        )
        lock_meta = _resolve_existing_alpha_refresh_lock(lock_key)
        if lock_meta is not None:
            return _build_alpha_refresh_conflict_response(
                alpha_scope=alpha_scope,
                target_date=target_date,
                top_n=top_n,
                universe_id=universe_id,
                portfolio_id=portfolio_id,
                pool_mode=pool_mode,
                lock_meta=lock_meta,
            )

        if not use_sync:
            celery_health = _get_dashboard_alpha_refresh_celery_health()
            if not bool(celery_health.get("available")):
                use_sync = True
                sync_reason = str(celery_health.get("reason") or "celery_unavailable")

        if use_sync:
            return _alpha_refresh_sync(
                lock_key=lock_key,
                target_date=target_date,
                top_n=top_n,
                raw_universe_id=raw_universe_id,
                alpha_scope=alpha_scope,
                portfolio_id=portfolio_id,
                pool_mode=pool_mode,
                resolved_pool=resolved_pool,
                sync_reason=sync_reason,
            )

        from apps.alpha.application.tasks import qlib_predict_scores

        if resolved_pool is None:
            if not acquire_dashboard_alpha_refresh_pending_lock(
                lock_key,
                meta=lock_meta_payload,
                timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
            ):
                lock_meta = _resolve_existing_alpha_refresh_lock(lock_key) or {
                    "status": "running",
                    "mode": "async",
                    "task_id": None,
                    "task_state": "PENDING",
                }
                return _build_alpha_refresh_conflict_response(
                    alpha_scope=alpha_scope,
                    target_date=target_date,
                    top_n=top_n,
                    universe_id=universe_id,
                    portfolio_id=portfolio_id,
                    pool_mode=pool_mode,
                    lock_meta=lock_meta,
                )
            task = qlib_predict_scores.delay(raw_universe_id, target_date.isoformat(), top_n)
            promote_dashboard_alpha_refresh_task_lock(
                lock_key,
                task_id=task.id,
                timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
            )
            message = (
                "已触发通用 Alpha 刷新任务；结果仅用于研究排名，不作为账户专属建议。"
                if alpha_scope == ALPHA_SCOPE_GENERAL
                else "已触发 Alpha 实时刷新任务，请稍后刷新查看最新结果。"
            )
            response_payload = {
                "success": True,
                "alpha_scope": alpha_scope,
                "task_id": task.id,
                "universe_id": raw_universe_id,
                "portfolio_id": portfolio_id,
                "scope_hash": None,
                "requested_trade_date": target_date.isoformat(),
                "pool_mode": pool_mode,
                "message": message,
                "poll_after_ms": 5000,
                "must_not_use_for_decision": True,
            }
        else:
            if not acquire_dashboard_alpha_refresh_pending_lock(
                lock_key,
                meta=lock_meta_payload,
                timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
            ):
                lock_meta = _resolve_existing_alpha_refresh_lock(lock_key) or {
                    "status": "running",
                    "mode": "async",
                    "task_id": None,
                    "task_state": "PENDING",
                }
                return _build_alpha_refresh_conflict_response(
                    alpha_scope=alpha_scope,
                    target_date=target_date,
                    top_n=top_n,
                    universe_id=universe_id,
                    portfolio_id=portfolio_id,
                    pool_mode=pool_mode,
                    lock_meta=lock_meta,
                )
            task = qlib_predict_scores.delay(
                resolved_pool.scope.universe_id,
                target_date.isoformat(),
                top_n,
                scope_payload=resolved_pool.scope.to_dict(),
            )
            promote_dashboard_alpha_refresh_task_lock(
                lock_key,
                task_id=task.id,
                timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
            )
            response_payload = {
                "success": True,
                "alpha_scope": ALPHA_SCOPE_PORTFOLIO,
                "task_id": task.id,
                "universe_id": resolved_pool.scope.universe_id,
                "portfolio_id": resolved_pool.portfolio_id,
                "scope_hash": resolved_pool.scope.scope_hash,
                "requested_trade_date": target_date.isoformat(),
                "pool_mode": resolved_pool.scope.pool_mode,
                "message": "已触发账户专属 scoped Qlib 推理任务，请稍后刷新查看最新结果。",
                "poll_after_ms": 5000,
                "must_not_use_for_decision": True,
            }
        return JsonResponse(response_payload)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception as exc:
        if "lock_key" in locals():
            release_dashboard_alpha_refresh_lock(lock_key)
        logger.error("Failed to trigger alpha realtime refresh: %s", exc, exc_info=True)
        return JsonResponse(
            {"success": False, "error": f"触发 Alpha 实时刷新失败: {exc}"},
            status=500,
        )


def _alpha_refresh_sync(
    *,
    lock_key: str,
    target_date,
    top_n,
    raw_universe_id,
    alpha_scope,
    portfolio_id,
    pool_mode,
    resolved_pool,
    sync_reason: str | None = None,
):
    """Run one scoped Qlib inference inline for dashboard manual refresh."""
    from apps.alpha.application.tasks import qlib_predict_scores

    universe_id = raw_universe_id
    scope_hash = None
    scope_payload = None
    if resolved_pool is not None:
        universe_id = resolved_pool.scope.universe_id
        scope_hash = resolved_pool.scope.scope_hash
        scope_payload = resolved_pool.scope.to_dict()

    sync_lock_meta = build_dashboard_alpha_refresh_metadata(
        alpha_scope=alpha_scope,
        target_date=target_date,
        top_n=top_n,
        universe_id=universe_id,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        scope_hash=scope_hash,
    )
    if not acquire_dashboard_alpha_refresh_pending_lock(
        lock_key,
        meta=sync_lock_meta,
        timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
    ):
        lock_meta = _resolve_existing_alpha_refresh_lock(lock_key) or {
            "status": "running",
            "mode": "sync",
            "task_id": None,
            "task_state": "RUNNING",
        }
        return _build_alpha_refresh_conflict_response(
            alpha_scope=alpha_scope,
            target_date=target_date,
            top_n=top_n,
            universe_id=universe_id,
            portfolio_id=portfolio_id,
            pool_mode=pool_mode,
            lock_meta=lock_meta,
        )

    try:
        promote_dashboard_alpha_refresh_task_lock(
            lock_key,
            task_id="__sync__",
            timeout=_ALPHA_REFRESH_LOCK_TTL_SECONDS,
            meta_updates=sync_lock_meta,
        )
        task_result = qlib_predict_scores.apply(
            args=[universe_id, target_date.isoformat(), top_n],
            kwargs={
                "scope_payload": scope_payload,
            },
        )
        result_payload = task_result.get(propagate=False)
        failed = bool(getattr(task_result, "failed", lambda: False)())

        if failed:
            logger.warning(
                "Sync alpha inference failed: universe=%s, trade_date=%s, result=%s",
                universe_id,
                target_date.isoformat(),
                result_payload,
            )
            return JsonResponse(
                {"success": False, "error": "同步推理失败，请检查 Qlib 运行状态。"},
                status=500,
            )

        if not isinstance(result_payload, dict) or result_payload.get("status") != "success":
            return JsonResponse(
                {
                    "success": False,
                    "error": "推理完成但无新结果（可能数据不足、数据未更新或非交易日）。",
                    "alpha_scope": alpha_scope,
                    "universe_id": universe_id,
                    "requested_trade_date": target_date.isoformat(),
                },
                status=200,
            )

        if result_payload.get("fallback_used"):
            message = "同步推理完成，但当前仍使用最近可用 Alpha cache；请先补齐 Qlib 基础数据。"
        elif result_payload.get("trade_date_adjusted"):
            effective_trade_date = result_payload.get("effective_trade_date") or result_payload.get(
                "qlib_data_latest_date"
            )
            message = f"同步推理完成，当前基于最近可用交易日 {effective_trade_date} 更新评分。"
        elif sync_reason == "no_active_workers":
            message = "未检测到 Celery worker，已改为同步推理并完成评分更新。"
        elif sync_reason == "unhealthy":
            message = "Celery 当前异常，已改为同步推理并完成评分更新。"
        elif sync_reason == "health_check_failed":
            message = "Celery 健康检查失败，已改为同步推理并完成评分更新。"
        else:
            message = "同步推理完成，已更新评分。"

        return JsonResponse({
            "success": True,
            "alpha_scope": alpha_scope,
            "task_id": None,
            "universe_id": universe_id,
            "portfolio_id": portfolio_id,
            "scope_hash": result_payload.get("scope_hash") or scope_hash,
            "requested_trade_date": target_date.isoformat(),
            "pool_mode": pool_mode,
            "message": message,
            "poll_after_ms": 1000,
            "sync": True,
            "sync_reason": sync_reason,
            "must_not_use_for_decision": True,
        })
    finally:
        release_dashboard_alpha_refresh_lock(lock_key)


@login_required(login_url="/account/login/")
def alpha_stocks_htmx(request):
    """
    HTMX Alpha 选股结果视图

    返回 Alpha 选股评分表格，支持动态刷新。
    """
    try:
        top_n = _parse_positive_int_param(
            request.GET.get('top_n', 10),
            field_name='top_n',
            default=10,
        )
        raw_portfolio_id = request.GET.get("portfolio_id")
        pool_mode = _normalize_dashboard_alpha_pool_mode(request.GET.get("pool_mode"))
        alpha_scope = normalize_alpha_scope(request.GET.get("alpha_scope"))
        portfolio_id = (
            _parse_positive_int_param(raw_portfolio_id, field_name="portfolio_id", default=0)
            if raw_portfolio_id not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    scores_payload = _get_alpha_stock_scores_payload(
        top_n=top_n,
        user=request.user,
        portfolio_id=None if alpha_scope == ALPHA_SCOPE_GENERAL else portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )
    scores = scores_payload["items"]
    meta = scores_payload["meta"]
    pool = scores_payload["pool"]
    actionable_candidates = scores_payload["actionable_candidates"]
    pending_requests = scores_payload["pending_requests"]
    recent_runs = scores_payload["recent_runs"]
    contract = _build_alpha_readiness_contract(
        meta=meta,
        top_candidates=scores,
        actionable_candidates=actionable_candidates,
        pending_requests=pending_requests,
    )

    if request.GET.get("format") == "json":
        return JsonResponse(
            {
                "success": True,
                "data": {
                    "items": scores,
                    "top_candidates": scores,
                    "actionable_candidates": actionable_candidates,
                    "pending_requests": pending_requests,
                    "meta": meta,
                    "pool": pool,
                    "recent_runs": recent_runs,
                    "history_run_id": scores_payload["history_run_id"],
                    "contract": contract,
                    "alpha_scope": alpha_scope,
                    "count": len(scores),
                    "top_n": top_n,
                },
            }
        )

    if 'HX-Request' not in request.headers:
        from django.shortcuts import redirect
        return redirect('dashboard:index')

    context = {
        'alpha_stocks': scores,
        'alpha_meta': meta,
        'alpha_pool': pool,
        'alpha_actionable_candidates': actionable_candidates,
        'alpha_pending_requests': pending_requests,
        'alpha_recent_runs': recent_runs,
        'alpha_history_run_id': scores_payload["history_run_id"],
        'selected_portfolio_id': portfolio_id or pool.get("portfolio_id"),
        'selected_alpha_pool_mode': pool_mode or pool.get("pool_mode"),
        'alpha_scope': alpha_scope,
        'alpha_pool_mode_choices': get_alpha_pool_mode_choices(),
        'top_n': top_n,
    }

    return render(request, 'dashboard/partials/alpha_stocks_table.html', context)


@login_required(login_url="/account/login/")
def alpha_history_page(request):
    """Dashboard Alpha recommendation history page."""
    portfolio_id = request.GET.get("portfolio_id")
    stock_code = str(request.GET.get("stock_code") or "").strip().upper() or None
    stage = str(request.GET.get("stage") or "").strip() or None
    source = str(request.GET.get("source") or "").strip() or None
    try:
        parsed_portfolio_id = (
            _parse_positive_int_param(portfolio_id, field_name="portfolio_id", default=0)
            if portfolio_id not in (None, "")
            else None
        )
    except ValueError:
        parsed_portfolio_id = None
    runs = get_alpha_homepage_query().list_history(
        user_id=request.user.id,
        portfolio_id=parsed_portfolio_id,
        stock_code=stock_code,
        stage=stage,
        source=source,
    )
    context = {
        "history_runs": runs,
        "filters": {
            "portfolio_id": parsed_portfolio_id,
            "stock_code": stock_code or "",
            "stage": stage or "",
            "source": source or "",
        },
    }
    return render(request, "dashboard/alpha_history.html", context)


@login_required(login_url="/account/login/")
def alpha_history_list_api(request):
    """Return recommendation history list for the current user."""
    portfolio_id = request.GET.get("portfolio_id")
    trade_date_raw = request.GET.get("trade_date")
    try:
        parsed_portfolio_id = (
            _parse_positive_int_param(portfolio_id, field_name="portfolio_id", default=0)
            if portfolio_id not in (None, "")
            else None
        )
        trade_date_value = date.fromisoformat(trade_date_raw) if trade_date_raw else None
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    runs = get_alpha_homepage_query().list_history(
        user_id=request.user.id,
        portfolio_id=parsed_portfolio_id,
        stock_code=str(request.GET.get("stock_code") or "").strip().upper() or None,
        stage=str(request.GET.get("stage") or "").strip() or None,
        source=str(request.GET.get("source") or "").strip() or None,
        trade_date=trade_date_value,
    )
    return JsonResponse({"success": True, "data": runs})


@login_required(login_url="/account/login/")
def alpha_history_detail_api(request, run_id: int):
    """Return a single historical recommendation run detail."""
    detail = get_alpha_homepage_query().get_history_detail(user_id=request.user.id, run_id=run_id)
    if detail is None:
        return JsonResponse({"success": False, "error": "历史记录不存在"}, status=404)
    return JsonResponse({"success": True, "data": detail})


@login_required(login_url="/account/login/")
def alpha_provider_status_htmx(request):
    """
    HTMX Alpha Provider 状态视图

    返回 Provider 状态面板 JSON 数据。
    """
    provider_status = _get_alpha_provider_status(user=request.user)

    return JsonResponse({
        'success': True,
        'data': provider_status,
        'status': provider_status.get('status', 'available'),
        'data_source': provider_status.get('data_source', 'live'),
        'warning_message': provider_status.get('warning_message'),
    })


@login_required(login_url="/account/login/")
def alpha_coverage_htmx(request):
    """
    HTMX Alpha 覆盖率指标视图

    返回覆盖率指标 JSON 数据。
    """
    coverage = _get_alpha_coverage_metrics(user=request.user)

    return JsonResponse({
        'success': True,
        'data': coverage,
        'status': coverage.get('status', 'available'),
        'data_source': coverage.get('data_source', 'live'),
        'warning_message': coverage.get('warning_message'),
    })


@login_required(login_url="/account/login/")
def alpha_ic_trends_htmx(request):
    """
    HTMX Alpha IC/ICIR 趋势图数据视图

    返回 IC 趋势 JSON 数据。
    """
    try:
        days = _parse_positive_int_param(
            request.GET.get('days', 30),
            field_name='days',
            default=30,
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)
    payload = _get_alpha_ic_trends_payload(days=days, user=request.user)

    return JsonResponse({
        'success': True,
        'data': payload['items'],
        'status': payload['status'],
        'data_source': payload['data_source'],
        'warning_message': payload['warning_message'],
    })


@login_required(login_url="/account/login/")
def alpha_factor_panel_htmx(request):
    """HTMX factor panel for a selected alpha stock."""
    if 'HX-Request' not in request.headers:
        return redirect('dashboard:index')

    stock_code = (request.GET.get('code') or '').strip()
    source = (request.GET.get('source') or '').strip() or None
    raw_portfolio_id = request.GET.get("portfolio_id")
    pool_mode = _normalize_dashboard_alpha_pool_mode(request.GET.get("pool_mode"))
    alpha_scope = normalize_alpha_scope(request.GET.get("alpha_scope"))
    try:
        top_n = _parse_positive_int_param(
            request.GET.get('top_n', 10),
            field_name='top_n',
            default=10,
        )
        portfolio_id = (
            _parse_positive_int_param(raw_portfolio_id, field_name="portfolio_id", default=0)
            if raw_portfolio_id not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    if not stock_code:
        return render(
            request,
            'dashboard/partials/alpha_factor_panel.html',
            {
                'stock': None,
                'stock_code': '',
                'provider': source or 'unknown',
                'factor_origin': '',
                'factors': [],
                'factor_count': 0,
                'empty_reason': '请选择左侧一只股票查看因子暴露。',
                'alpha_scope': alpha_scope,
                'alpha_meta': {},
                'alpha_pool': {},
                'recommendation_basis': {},
                'factor_basis': [],
                'buy_reasons': [],
                'no_buy_reasons': [],
                'risk_snapshot': {},
            },
        )

    context = _build_alpha_factor_panel(
        stock_code=stock_code,
        source=source,
        top_n=top_n,
        user=request.user,
        portfolio_id=portfolio_id,
        pool_mode=pool_mode,
        alpha_scope=alpha_scope,
    )
    return render(request, 'dashboard/partials/alpha_factor_panel.html', context)
