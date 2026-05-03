"""
Core Context Processors

提供全局上下文数据，包括告警信息和视觉约定。
"""

import logging

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


def _should_use_default_market_visuals(request) -> bool:
    """Return whether one auth-page request can skip runtime visual lookup."""

    if request is None:
        return False

    path = getattr(request, "path", "")
    if not path.startswith(_AUTH_PAGE_PATH_PREFIXES):
        return False

    user = getattr(request, "user", None)
    return not getattr(user, "is_authenticated", False)


def get_market_visuals(request) -> dict[str, dict[str, str]]:
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
        logger.warning("Failed to load market visual tokens: %s", exc)
        visual_tokens = dict(_DEFAULT_MARKET_VISUALS)
    return {"market_visuals": visual_tokens}


def get_alerts(request) -> dict[str, list[dict[str, str]]]:
    """
    获取当前用户的告警信息

    告警类型：
    - 配额即将耗尽（剩余 < 20%）
    - 配额已耗尽
    - 触发器即将过期
    - 候选即将过期
    - Regime/Policy 变化通知
    """
    if not request.user.is_authenticated:
        return {'global_alerts': []}

    alerts = []

    try:
        # ========== 配额告警 ==========
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            quota_usage = (
                get_decision_rhythm_global_alert_service().get_weekly_quota_usage()
            )
            if quota_usage:
                quota_remaining = quota_usage["quota_remaining"]
                usage_percent = quota_usage["usage_percent"]
                if usage_percent >= 100:
                    alerts.append({
                        'type': 'danger',
                        'icon': '🚨',
                        'title': '配额已耗尽',
                        'message': '本周决策配额已用完。请联系管理员或重置配额。',
                        'action_url': '/decision-rhythm/quota/',
                        'action_text': '查看配额',
                        'dismissible': True,
                    })
                elif usage_percent >= 80:
                    alerts.append({
                        'type': 'warning',
                        'icon': '⚠️',
                        'title': '配额即将耗尽',
                        'message': f'本周剩余配额仅 {quota_remaining} 次（已使用 {usage_percent}%）。',
                        'action_url': '/decision-rhythm/quota/',
                        'action_text': '查看详情',
                        'dismissible': True,
                    })
        except Exception as e:
            logger.warning(f"Failed to check quota alerts: {e}")

        # ========== 候选即将过期告警 ==========
        try:
            from apps.alpha_trigger.application.global_alert_service import (
                get_alpha_trigger_global_alert_service,
            )

            expiring_candidates = (
                get_alpha_trigger_global_alert_service().count_expiring_candidates()
            )
            if expiring_candidates > 0:
                alerts.append({
                    'type': 'info',
                    'icon': '⏰',
                    'title': f'{expiring_candidates} 个 Alpha 候选即将过期',
                    'message': '请在过期前处理相关投资机会或更新触发器配置。',
                        'action_url': '/alpha-triggers/',
                    'action_text': '查看候选',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check expiring candidates: {e}")

        # ========== 触发器即将过期告警 ==========
        try:
            from apps.alpha_trigger.application.global_alert_service import (
                get_alpha_trigger_global_alert_service,
            )

            expiring_triggers = (
                get_alpha_trigger_global_alert_service().count_expiring_triggers()
            )
            if expiring_triggers > 0:
                alerts.append({
                    'type': 'info',
                    'icon': '⏳',
                    'title': f'{expiring_triggers} 个触发器即将过期',
                    'message': '这些触发器将在一周内失效，请考虑续期或重新配置。',
                        'action_url': '/alpha-triggers/',
                    'action_text': '查看触发器',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check expiring triggers: {e}")

        # ========== 冷却期活跃提示 ==========
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            active_cooldowns = (
                get_decision_rhythm_global_alert_service().count_active_cooldowns()
            )
            if active_cooldowns > 5:
                alerts.append({
                    'type': 'info',
                    'icon': '❄️',
                    'title': f'{active_cooldowns} 个资产处于冷却期',
                    'message': '这些资产暂时无法提交新的决策请求。',
                    'action_url': '/decision-rhythm/quota/',
                    'action_text': '查看详情',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check active cooldowns: {e}")

        # ========== 高优先级待处理请求告警 ==========
        try:
            from apps.decision_rhythm.application.global_alert_service import (
                get_decision_rhythm_global_alert_service,
            )

            high_priority_count = (
                get_decision_rhythm_global_alert_service().count_high_priority_pending_requests()
            )
            if high_priority_count > 0:
                alerts.append({
                    'type': 'warning',
                    'icon': '🔥',
                    'title': f'{high_priority_count} 个高优先级请求待处理',
                    'message': '请及时处理这些紧急决策请求。',
                    'action_url': '/decision/workspace/',
                    'action_text': '立即处理',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check pending requests: {e}")

        # ========== Beta Gate 配置失效告警 ==========
        try:
            from apps.beta_gate.application.config_summary_service import (
                get_beta_gate_config_summary_service,
            )

            beta_gate_summary = (
                get_beta_gate_config_summary_service().get_beta_gate_summary(request.user)
            )
            if beta_gate_summary.get("status") == "missing":
                alerts.append({
                    'type': 'warning',
                    'icon': '🚪',
                    'title': 'Beta Gate 未配置',
                    'message': '请配置 Beta Gate 以启用资产可见性过滤功能。',
                    'action_url': '/beta-gate/config/',
                    'action_text': '立即配置',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check beta gate config: {e}")

        # ========== 可操作候选数量告警 ==========
        try:
            from apps.alpha_trigger.application.global_alert_service import (
                get_alpha_trigger_global_alert_service,
            )

            actionable_count = (
                get_alpha_trigger_global_alert_service().count_actionable_candidates()
            )
            if actionable_count > 10:
                alerts.append({
                    'type': 'success',
                    'icon': '⚡',
                    'title': f'{actionable_count} 个候选可行动',
                    'message': '有多个投资机会等待处理，建议尽快决策。',
                    'action_url': '/decision/workspace/',
                    'action_text': '查看工作台',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check actionable candidates: {e}")

    except Exception as e:
        logger.error(f"Error getting alerts: {e}", exc_info=True)

    return {'global_alerts': alerts}
