"""Regime, pulse, thermometer, and action context helpers."""

# ruff: noqa: I001

import logging
from datetime import date
from typing import Any, cast

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
from apps.dashboard.application.use_cases import DashboardData
from apps.data_center.application import interface_services as data_center_interface_services
from apps.pulse.domain.entities import PulseSnapshot
from apps.regime.domain.action_mapper import RegimeActionRecommendation
from apps.regime.domain.entities import RegimeNavigatorOutput
from shared.numeric import safe_float

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
) -> tuple[
    RegimeNavigatorOutput | None,
    PulseSnapshot | None,
    RegimeActionRecommendation | None,
]:
    """Load navigator, pulse, and action recommendation objects for dashboard widgets."""
    components = dashboard_interface_services.load_phase1_macro_components(
        as_of_date=as_of_date,
        refresh_if_stale=refresh_if_stale,
    )
    return (
        cast(RegimeNavigatorOutput | None, components.navigator),
        cast(PulseSnapshot | None, components.pulse),
        cast(RegimeActionRecommendation | None, components.action),
    )


def _score_to_percent(score: float) -> int:
    """Map a pulse score in [-1, 1] to a percentage width in [0, 100]."""
    normalized_score = safe_float(score)
    if normalized_score is None:
        return 0
    bounded = max(-1.0, min(1.0, normalized_score))
    return int(round((bounded + 1.0) * 50))


def _parse_positive_int_param(
    raw_value: object,
    *,
    field_name: str,
    default: int | None = None,
) -> int | None:
    """Parse optional positive-int query params used by HTMX/API endpoints."""
    if raw_value in (None, ""):
        return default

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, str)):
        raise ValueError(f"{field_name} 必须是整数")

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


def _fraction_to_percent(value: object) -> float | None:
    """Convert a validated [0, 1] fraction to a display percentage."""

    normalized = safe_float(value)
    if normalized is None or not 0.0 <= normalized <= 1.0:
        return None
    return normalized * 100


def _pulse_is_display_reliable(pulse: PulseSnapshot | None) -> bool:
    """Require a complete finite four-dimension snapshot for dashboard decisions."""

    if pulse is None or not pulse.is_reliable:
        return False
    dimensions = {entry.dimension: entry for entry in pulse.dimension_scores}
    expected_dimensions = {"growth", "inflation", "liquidity", "sentiment"}
    return (
        safe_float(pulse.composite_score) is not None
        and expected_dimensions.issubset(dimensions)
        and all(safe_float(dimensions[name].score) is not None for name in expected_dimensions)
    )


def _build_regime_status_context(
    navigator: RegimeNavigatorOutput | None,
    pulse: PulseSnapshot | None,
    action: RegimeActionRecommendation | None,
) -> dict[str, Any]:
    """Build template context for the regime status bar widget."""
    movement = getattr(navigator, "movement", None)
    action_blocked = action is None or action.must_not_use_for_decision
    confidence_pct = _fraction_to_percent(navigator.confidence) if navigator is not None else None
    risk_budget_pct = (
        _fraction_to_percent(action.risk_budget_pct)
        if action is not None and not action_blocked
        else None
    )
    pulse_is_reliable = _pulse_is_display_reliable(pulse)

    return {
        "regime_name": navigator.regime_name if navigator else "Unknown",
        "is_transitioning": bool(navigator and navigator.is_transitioning),
        "transition_target": movement.transition_target if movement else None,
        "confidence_pct": confidence_pct,
        "pulse_strength": pulse.regime_strength if pulse else "unavailable",
        "risk_budget_pct": risk_budget_pct,
        "transition_warning": bool(pulse and pulse.transition_warning),
        "action_blocked": action_blocked,
        "must_not_use_for_decision": bool(
            navigator is None
            or confidence_pct is None
            or not pulse_is_reliable
            or action_blocked
            or risk_budget_pct is None
        ),
    }


def _build_pulse_card_context(pulse: PulseSnapshot | None) -> dict[str, Any]:
    """Build template context for the Pulse dashboard widget."""
    dimensions = {ds.dimension: ds for ds in getattr(pulse, "dimension_scores", [])}

    def _dimension_score(name: str) -> float:
        entry = dimensions.get(name)
        score = safe_float(entry.score if entry else None)
        return score if score is not None else 0.0

    def _dimension_signal(name: str) -> str:
        entry = dimensions.get(name)
        return entry.signal if entry else "neutral"

    return {
        "pulse_observed_at": pulse.observed_at.isoformat() if pulse else "",
        "pulse_composite": safe_float(pulse.composite_score) if pulse else None,
        "pulse_strength": pulse.regime_strength if pulse else "unavailable",
        "growth_score": _dimension_score("growth"),
        "growth_signal": _dimension_signal("growth"),
        "growth_pct": _score_to_percent(_dimension_score("growth")),
        "inflation_score": _dimension_score("inflation"),
        "inflation_signal": _dimension_signal("inflation"),
        "inflation_pct": _score_to_percent(_dimension_score("inflation")),
        "liquidity_score": _dimension_score("liquidity"),
        "liquidity_signal": _dimension_signal("liquidity"),
        "liquidity_pct": _score_to_percent(_dimension_score("liquidity")),
        "sentiment_score": _dimension_score("sentiment"),
        "sentiment_signal": _dimension_signal("sentiment"),
        "sentiment_pct": _score_to_percent(_dimension_score("sentiment")),
        "pulse_transition_warning": bool(pulse and pulse.transition_warning),
        "pulse_transition_direction": getattr(pulse, "transition_direction", None),
        "pulse_transition_reasons": getattr(pulse, "transition_reasons", []),
        "pulse_is_reliable": _pulse_is_display_reliable(pulse),
        "pulse_stale_count": getattr(pulse, "stale_indicator_count", 0),
    }


def _load_market_thermometer_payload(user_id: int | None) -> dict[str, Any]:
    """Load the latest market thermometer payload via the data-center boundary."""

    if user_id is None:
        return {}
    return data_center_interface_services.load_market_thermometer_payload(
        user_id=user_id,
        use_personal_thresholds=True,
    )


def _build_market_thermometer_context(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build template context for the market-thermometer dashboard widget."""

    payload = dict(payload or {})
    raw_components = payload.get("components")
    components = (
        [item for item in raw_components if isinstance(item, dict)]
        if isinstance(raw_components, list)
        else []
    )

    def _component_contribution(item: dict[str, Any]) -> float:
        score = safe_float(item.get("score"), default=0.0)
        weight = safe_float(item.get("weight"), default=0.0)
        return (score or 0.0) * (weight or 0.0)

    sorted_components = sorted(
        components,
        key=_component_contribution,
        reverse=True,
    )
    raw_reasons = payload.get("trigger_reasons")
    top_reasons = list(raw_reasons)[:3] if isinstance(raw_reasons, list) else []
    score = safe_float(payload.get("score"))
    score_available = bool(payload.get("score_available", score is not None)) and score is not None
    band = str(payload.get("effective_band") or payload.get("band") or "unavailable")
    if band not in {"cold", "warm", "hot", "overheat", "extreme"}:
        score_available = False
    if not score_available:
        band = "unavailable"
    change_5d = safe_float(payload.get("change_5d"))
    change_20d = safe_float(payload.get("change_20d"))
    return {
        "market_temperature_observed_at": payload.get("observed_at"),
        "market_temperature_score": score if score_available else None,
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
            "↑" if (change_5d or 0.0) > 0 else ("↓" if (change_5d or 0.0) < 0 else "→")
        ),
        "market_temperature_change_20d_arrow": (
            "↑" if (change_20d or 0.0) > 0 else ("↓" if (change_20d or 0.0) < 0 else "→")
        ),
        "market_temperature_is_hot": band in {"hot", "overheat", "extreme"},
        "market_temperature_is_overheat": band in {"overheat", "extreme"},
        "market_temperature_threshold_source": payload.get("threshold_source", "system"),
        "market_temperature_components": sorted_components,
        "market_temperature_top_reasons": top_reasons,
        "market_temperature_degraded": bool(payload.get("must_not_use_for_decision", False)),
        "market_temperature_blocked_reason": payload.get("blocked_reason", ""),
    }


def _build_action_recommendation_context(
    action: RegimeActionRecommendation | None,
) -> dict[str, Any]:
    """Build template context for the action recommendation widget."""
    if not action:
        return {
            "action_weights": {},
            "action_risk_budget": None,
            "action_position_limit": None,
            "action_sectors": [],
            "action_styles": [],
            "action_hedge": None,
            "action_regime_contribution": "",
            "action_pulse_contribution": "",
            "action_reasoning": "当前暂无联合行动建议，请先完成 Regime 与 Pulse 数据计算。",
            "action_confidence": None,
            "action_blocked": True,
            "action_blocked_reason": "当前暂无联合行动建议。",
            "action_blocked_code": "action_unavailable",
            "action_stale_indicator_codes": [],
            "must_not_use_for_decision": True,
        }

    is_blocked = action.must_not_use_for_decision
    action_weights = (
        {
            category: percentage
            for category, weight in action.asset_weights.items()
            if (percentage := _fraction_to_percent(weight)) is not None
        }
        if not is_blocked
        else {}
    )
    return {
        "action_weights": action_weights,
        "action_risk_budget": (
            _fraction_to_percent(action.risk_budget_pct) if not is_blocked else None
        ),
        "action_position_limit": (
            _fraction_to_percent(action.position_limit_pct) if not is_blocked else None
        ),
        "action_sectors": action.recommended_sectors if not is_blocked else [],
        "action_styles": action.benefiting_styles if not is_blocked else [],
        "action_hedge": action.hedge_recommendation if not is_blocked else None,
        "action_regime_contribution": action.regime_contribution,
        "action_pulse_contribution": action.pulse_contribution,
        "action_reasoning": action.reasoning,
        "action_confidence": _fraction_to_percent(action.confidence),
        "action_blocked": is_blocked,
        "action_blocked_reason": getattr(action, "blocked_reason", ""),
        "action_blocked_code": getattr(action, "blocked_code", ""),
        "action_stale_indicator_codes": list(getattr(action, "stale_indicator_codes", []) or []),
        "must_not_use_for_decision": is_blocked,
    }


def _build_attention_items_context(
    data: DashboardData,
    navigator: RegimeNavigatorOutput | None,
    pulse: PulseSnapshot | None,
    market_thermometer: dict[str, Any] | None = None,
) -> dict[str, Any]:
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


def _build_browser_notification_context(
    navigator: RegimeNavigatorOutput | None,
    pulse: PulseSnapshot | None,
) -> dict[str, Any]:
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
        "browser_notification_enabled": payload is not None,
        "browser_notification_payload": payload,
    }


# ========================================
# Alpha 可视化数据获取函数（委托至 Query Services）
# ========================================
