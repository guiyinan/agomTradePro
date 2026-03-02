"""
Core Context Processors

提供全局上下文数据，包括告警信息。
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def get_alerts(request) -> Dict[str, List[Dict[str, str]]]:
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
        from django.utils import timezone
        from datetime import timedelta

        # ========== 配额告警 ==========
        try:
            from apps.decision_rhythm.infrastructure.models import DecisionQuotaModel
            from apps.decision_rhythm.domain.entities import QuotaPeriod
            current_quota = (
                DecisionQuotaModel._default_manager
                .filter(period=QuotaPeriod.WEEKLY.value)
                .order_by('-period_start')
                .first()
            )

            if current_quota:
                quota_total = getattr(current_quota, 'max_decisions', 10)
                quota_used = getattr(current_quota, 'used_decisions', 0)
                quota_remaining = max(0, quota_total - quota_used)
                usage_percent = round(quota_used / quota_total * 100, 1) if quota_total > 0 else 0

                if usage_percent >= 100:
                    alerts.append({
                        'type': 'danger',
                        'icon': '🚨',
                        'title': '配额已耗尽',
                        'message': f'本周决策配额已用完。请联系管理员或重置配额。',
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
            from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
            # AlphaCandidateModel 无 expires_at 字段，基于 created_at + time_horizon 近似计算
            expiring_candidates = 0
            now = timezone.now()
            threshold = now + timedelta(days=2)
            candidates = AlphaCandidateModel._default_manager.filter(
                status__in=['WATCH', 'CANDIDATE', 'ACTIONABLE']
            ).only('created_at', 'time_horizon')
            for c in candidates:
                if not c.created_at or not c.time_horizon:
                    continue
                expires_at = c.created_at + timedelta(days=int(c.time_horizon))
                if now < expires_at <= threshold:
                    expiring_candidates += 1

            if expiring_candidates > 0:
                alerts.append({
                    'type': 'info',
                    'icon': '⏰',
                    'title': f'{expiring_candidates} 个 Alpha 候选即将过期',
                    'message': '请在过期前处理相关投资机会或更新触发器配置。',
                    'action_url': '/alpha-triggers/list/',
                    'action_text': '查看候选',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check expiring candidates: {e}")

        # ========== 触发器即将过期告警 ==========
        try:
            from apps.alpha_trigger.infrastructure.models import AlphaTriggerModel
            trigger_threshold = timezone.now() + timedelta(days=7)
            expiring_triggers = AlphaTriggerModel._default_manager.filter(
                status='ACTIVE',
                expires_at__lte=trigger_threshold,
                expires_at__gt=timezone.now()
            ).count()

            if expiring_triggers > 0:
                alerts.append({
                    'type': 'info',
                    'icon': '⏳',
                    'title': f'{expiring_triggers} 个触发器即将过期',
                    'message': '这些触发器将在一周内失效，请考虑续期或重新配置。',
                    'action_url': '/alpha-triggers/list/',
                    'action_text': '查看触发器',
                    'dismissible': True,
                })
        except Exception as e:
            logger.warning(f"Failed to check expiring triggers: {e}")

        # ========== 冷却期活跃提示 ==========
        try:
            from apps.decision_rhythm.infrastructure.models import CooldownPeriodModel
            # 当前模型无 status 字段：以近 72 小时内有决策行为的冷却记录作为活跃近似
            active_cooldowns = CooldownPeriodModel._default_manager.filter(
                last_decision_at__gte=timezone.now() - timedelta(hours=72)
            ).count()

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
            from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
            high_priority_count = DecisionRequestModel._default_manager.filter(
                execution_status='PENDING',
                priority='high'
            ).count()

            if high_priority_count > 0:
                alerts.append({
                    'type': 'warning',
                    'icon': '🔥',
                    'title': f'{high_priority_count} 个高优先级请求待处理',
                    'message': '请及时处理这些紧急决策请求。',
                    'action_url': '/decision/workspace/',
                    'action_text': '立即处理',
                    'dismissible': False,
                })
        except Exception as e:
            logger.warning(f"Failed to check pending requests: {e}")

        # ========== Beta Gate 配置失效告警 ==========
        try:
            from apps.beta_gate.infrastructure.models import GateConfigModel
            active_config = GateConfigModel._default_manager.active().first()

            if not active_config:
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
            from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
            actionable_count = AlphaCandidateModel._default_manager.filter(
                status='ACTIONABLE'
            ).count()

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


