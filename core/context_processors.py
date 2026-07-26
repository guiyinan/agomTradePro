"""
Core Context Processors

提供全局上下文数据，包括告警信息和视觉约定。
"""

import logging
from typing import TypedDict

from django.http import HttpRequest

from core.ui_modes import UI_MODE_CLASSIC, UI_MODE_COOKIE, VALID_UI_MODES
from shared.numeric import safe_float

logger = logging.getLogger(__name__)

_DEFAULT_MARKET_VISUALS = {
    "rise": "var(--color-error)",
    "fall": "var(--color-success)",
    "rise_soft": "var(--color-error-light)",
    "fall_soft": "var(--color-success-light)",
    "rise_strong": "var(--color-error-dark)",
    "fall_strong": "var(--color-success-dark)",
    "inflow": "var(--color-error)",
    "outflow": "var(--color-success)",
    "convention": "cn_a_share",
    "label": "A股红涨绿跌",
}
_AUTH_PAGE_PATH_PREFIXES = ("/account/login/", "/account/register/")


class GlobalAlert(TypedDict):
    """One bounded user-facing global alert."""

    type: str
    icon: str
    title: str
    message: str
    action_url: str
    action_text: str
    dismissible: bool


def _nonnegative_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _log_context_failure(operation: str, exc: Exception) -> None:
    logger.warning(
        "Global context lookup failed: operation=%s error_type=%s",
        operation,
        type(exc).__name__,
    )


def get_ui_mode(request: HttpRequest | None) -> dict[str, object]:
    """Return the browser-selected UI mode for template chrome."""

    raw_mode = ""
    if request is not None:
        raw_mode = str(getattr(request, "COOKIES", {}).get(UI_MODE_COOKIE, "") or "")
    ui_mode = raw_mode if raw_mode in VALID_UI_MODES else UI_MODE_CLASSIC
    return {
        "ui_mode": ui_mode,
        "is_tui_mode": ui_mode != UI_MODE_CLASSIC,
    }


def _should_use_default_market_visuals(request: HttpRequest | None) -> bool:
    """Return whether one auth-page request can skip runtime visual lookup."""

    if request is None:
        return False

    path = getattr(request, "path", "")
    if not path.startswith(_AUTH_PAGE_PATH_PREFIXES):
        return False

    user = getattr(request, "user", None)
    return not getattr(user, "is_authenticated", False)


def get_market_visuals(request: HttpRequest | None) -> dict[str, dict[str, str]]:
    """
    获取全局市场语义颜色配置。

    所有行情相关页面应消费 rise/fall/inflow/outflow 等语义 token，
    而不是直接硬编码 red/green。
    """
    if _should_use_default_market_visuals(request):
        return {"market_visuals": dict(_DEFAULT_MARKET_VISUALS)}

    try:
        from apps.account.application.config_summary_service import (
            get_account_config_summary_service,
        )

        visual_tokens = get_account_config_summary_service().get_market_visual_tokens()
    except Exception as exc:
        _log_context_failure("market_visuals", exc)
        visual_tokens = dict(_DEFAULT_MARKET_VISUALS)
    return {"market_visuals": visual_tokens}


def get_alerts(request: HttpRequest) -> dict[str, list[GlobalAlert]]:
    """
    获取当前用户的告警信息

    告警类型：
    - 配额即将耗尽（剩余 < 20%）
    - 配额已耗尽
    - 触发器即将过期
    - 候选即将过期
    - Regime/Policy 变化通知
    """
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {"global_alerts": []}

    alerts: list[GlobalAlert] = []

    try:
        from apps.decision_rhythm.application.global_alert_service import (
            get_decision_rhythm_global_alert_service,
        )

        decision_service = get_decision_rhythm_global_alert_service()
    except Exception as exc:
        _log_context_failure("decision_alert_service", exc)
        decision_service = None

    if decision_service is not None:
        try:
            quota_usage = decision_service.get_weekly_quota_usage()
            if quota_usage:
                quota_remaining = _nonnegative_count(quota_usage["quota_remaining"])
                usage_percent = safe_float(quota_usage["usage_percent"])
                if usage_percent is not None and usage_percent >= 100:
                    alerts.append(
                        {
                            "type": "danger",
                            "icon": "🚨",
                            "title": "配额已耗尽",
                            "message": "本周决策配额已用完。请联系管理员或重置配额。",
                            "action_url": "/decision-rhythm/quota/",
                            "action_text": "查看配额",
                            "dismissible": True,
                        }
                    )
                elif usage_percent is not None and usage_percent >= 80:
                    alerts.append(
                        {
                            "type": "warning",
                            "icon": "⚠️",
                            "title": "配额即将耗尽",
                            "message": (
                                f"本周剩余配额仅 {quota_remaining} 次"
                                f"（已使用 {usage_percent}%）。"
                            ),
                            "action_url": "/decision-rhythm/quota/",
                            "action_text": "查看详情",
                            "dismissible": True,
                        }
                    )
        except Exception as exc:
            _log_context_failure("quota_alert", exc)

        try:
            active_cooldowns = _nonnegative_count(decision_service.count_active_cooldowns())
            if active_cooldowns > 5:
                alerts.append(
                    {
                        "type": "info",
                        "icon": "❄️",
                        "title": f"{active_cooldowns} 个资产处于冷却期",
                        "message": "这些资产暂时无法提交新的决策请求。",
                        "action_url": "/decision-rhythm/quota/",
                        "action_text": "查看详情",
                        "dismissible": True,
                    }
                )
        except Exception as exc:
            _log_context_failure("active_cooldown_alert", exc)

        try:
            high_priority_count = _nonnegative_count(
                decision_service.count_high_priority_pending_requests()
            )
            if high_priority_count > 0:
                alerts.append(
                    {
                        "type": "warning",
                        "icon": "🔥",
                        "title": f"{high_priority_count} 个高优先级请求待处理",
                        "message": "请及时处理这些紧急决策请求。",
                        "action_url": "/decision/workspace/",
                        "action_text": "立即处理",
                        "dismissible": True,
                    }
                )
        except Exception as exc:
            _log_context_failure("pending_request_alert", exc)

    try:
        from apps.alpha_trigger.application.global_alert_service import (
            get_alpha_trigger_global_alert_service,
        )

        alpha_service = get_alpha_trigger_global_alert_service()
    except Exception as exc:
        _log_context_failure("alpha_alert_service", exc)
        alpha_service = None

    if alpha_service is not None:
        try:
            expiring_candidates = _nonnegative_count(alpha_service.count_expiring_candidates())
            if expiring_candidates > 0:
                alerts.append(
                    {
                        "type": "info",
                        "icon": "⏰",
                        "title": f"{expiring_candidates} 个 Alpha 候选即将过期",
                        "message": "请在过期前处理相关投资机会或更新触发器配置。",
                        "action_url": "/alpha-triggers/",
                        "action_text": "查看候选",
                        "dismissible": True,
                    }
                )
        except Exception as exc:
            _log_context_failure("expiring_candidate_alert", exc)

        try:
            expiring_triggers = _nonnegative_count(alpha_service.count_expiring_triggers())
            if expiring_triggers > 0:
                alerts.append(
                    {
                        "type": "info",
                        "icon": "⏳",
                        "title": f"{expiring_triggers} 个触发器即将过期",
                        "message": "这些触发器将在一周内失效，请考虑续期或重新配置。",
                        "action_url": "/alpha-triggers/",
                        "action_text": "查看触发器",
                        "dismissible": True,
                    }
                )
        except Exception as exc:
            _log_context_failure("expiring_trigger_alert", exc)

        try:
            actionable_count = _nonnegative_count(alpha_service.count_actionable_candidates())
            if actionable_count > 10:
                alerts.append(
                    {
                        "type": "success",
                        "icon": "⚡",
                        "title": f"{actionable_count} 个候选可行动",
                        "message": "有多个投资机会等待处理，建议尽快决策。",
                        "action_url": "/decision/workspace/",
                        "action_text": "查看工作台",
                        "dismissible": True,
                    }
                )
        except Exception as exc:
            _log_context_failure("actionable_candidate_alert", exc)

    try:
        from apps.beta_gate.application.config_summary_service import (
            get_beta_gate_config_summary_service,
        )

        beta_gate_summary = get_beta_gate_config_summary_service().get_beta_gate_summary(user)
        if beta_gate_summary.get("status") == "missing":
            alerts.append(
                {
                    "type": "warning",
                    "icon": "🚪",
                    "title": "Beta Gate 未配置",
                    "message": "请配置 Beta Gate 以启用资产可见性过滤功能。",
                    "action_url": "/beta-gate/config/",
                    "action_text": "立即配置",
                    "dismissible": True,
                }
            )
    except Exception as exc:
        _log_context_failure("beta_gate_alert", exc)

    return {"global_alerts": alerts}
