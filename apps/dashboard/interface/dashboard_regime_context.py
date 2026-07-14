"""Regime, pulse, thermometer, and action context helpers."""

# ruff: noqa: I001

import logging
from datetime import date

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
    ALPHA_POOL_MODE_PRICE_COVERED,
)
from apps.alpha.application.pool_resolver import (
    PortfolioAlphaPoolResolver as _PortfolioAlphaPoolResolver,
)
from apps.alpha.application.pool_resolver import (
    normalize_alpha_pool_mode,
)
from apps.alpha.application.trade_dates import (
    resolve_recent_closed_trade_date as _resolve_dashboard_alpha_trade_date,
)
from apps.dashboard.application import interface_services as dashboard_interface_services
from apps.data_center.application import interface_services as data_center_interface_services

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


def _load_market_thermometer_payload(user_id: int | None) -> dict:
    """Load the latest market thermometer payload via the data-center boundary."""

    if user_id is None:
        return {}
    return data_center_interface_services.load_market_thermometer_payload(
        user_id=user_id,
        use_personal_thresholds=True,
    )


def _build_market_thermometer_context(payload: dict | None) -> dict:
    """Build template context for the market-thermometer dashboard widget."""

    payload = dict(payload or {})
    components = list(payload.get("components") or [])
    sorted_components = sorted(
        components,
        key=lambda item: float(item.get("score", 0.0)) * float(item.get("weight", 0.0)),
        reverse=True,
    )
    top_reasons = list(payload.get("trigger_reasons") or [])[:3]
    score_available = bool(payload.get("score_available", True))
    band = str(payload.get("effective_band") or payload.get("band") or "cold")
    if not score_available:
        band = "unavailable"
    change_5d = payload.get("change_5d")
    change_20d = payload.get("change_20d")
    return {
        "market_temperature_observed_at": payload.get("observed_at"),
        "market_temperature_score": (
            float(payload.get("score", 0.0) or 0.0) if score_available else None
        ),
        "market_temperature_score_available": score_available,
        "market_temperature_band": band,
        "market_temperature_band_label": {
            "cold": "冷",
            "warm": "温",
            "hot": "热",
            "overheat": "过热",
            "extreme": "极热",
            "unavailable": "数据缺失",
        }.get(band, band),
        "market_temperature_change_5d": change_5d,
        "market_temperature_change_20d": change_20d,
        "market_temperature_change_5d_arrow": (
            "↑" if (change_5d or 0) > 0 else ("↓" if (change_5d or 0) < 0 else "→")
        ),
        "market_temperature_change_20d_arrow": (
            "↑" if (change_20d or 0) > 0 else ("↓" if (change_20d or 0) < 0 else "→")
        ),
        "market_temperature_is_hot": band in {"hot", "overheat", "extreme"},
        "market_temperature_is_overheat": band in {"overheat", "extreme"},
        "market_temperature_threshold_source": payload.get("threshold_source", "system"),
        "market_temperature_components": sorted_components,
        "market_temperature_top_reasons": top_reasons,
        "market_temperature_degraded": bool(payload.get("must_not_use_for_decision", False)),
        "market_temperature_blocked_reason": payload.get("blocked_reason", ""),
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


def _build_attention_items_context(
    data, navigator, pulse, market_thermometer: dict | None = None
) -> dict:
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
                    f"优先处理 {first_signal.get('asset_code', '未知标的')}" " 的已批准信号。"
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

    if market_thermometer:
        band = str(market_thermometer.get("effective_band") or market_thermometer.get("band") or "")
        if band in {"overheat", "extreme"}:
            items.append(
                {
                    "level": "high",
                    "title": "市场温度过高",
                    "detail": "谨慎追高，避免情绪化加仓，优先复核仓位与风控阈值。",
                    "meta": "来源: market_thermometer",
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
        reasons = (
            "；".join((pulse.transition_reasons or [])[:2]) or "多维脉搏与当前 Regime 产生冲突。"
        )
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
