"""
Application Layer - Celery Tasks for Policy Management

定义异步任务，如定时检查、告警发送等。
"""

import logging
from datetime import date, timedelta
from typing import Optional, Dict, Any

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db.models import Count, Q

from ..domain.entities import PolicyLevel, PolicyEvent
from ..infrastructure.repositories import DjangoPolicyRepository
from .use_cases import GetPolicyStatusUseCase

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5分钟后重试
)
def check_policy_status_alert(self, as_of_date_str: Optional[str] = None):
    """
    定时检查政策状态并发送告警（如需要）

    该任务应由 Celery Beat 定时调用（如每小时一次）

    Args:
        as_of_date_str: 日期字符串 (YYYY-MM-DD)，None 表示今天
    """
    try:
        as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()

        repo = DjangoPolicyRepository()
        use_case = GetPolicyStatusUseCase(event_store=repo)

        status = use_case.execute(as_of_date)

        # 检查是否需要告警
        if status.current_level in [PolicyLevel.P2, PolicyLevel.P3]:
            # 获取最新事件
            latest = status.latest_event
            if latest:
                _send_policy_alert(
                    level=status.current_level,
                    event=latest,
                    status=status
                )

        logger.info(f"Policy status check completed for {as_of_date}")

        return {
            "status": "success",
            "level": status.current_level.value,
            "date": as_of_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Policy status check failed: {e}", exc_info=True)
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for policy status check")
            raise


@shared_task
def monitor_policy_transitions():
    """
    监控政策档位变更

    检查最近 24 小时内是否有档位变更，如有则发送摘要
    """
    try:
        repo = DjangoPolicyRepository()

        today = date.today()
        yesterday = today - timedelta(days=1)

        # 获取最近的事件
        recent_events = repo.get_events_in_range(yesterday, today)

        if len(recent_events) > 1:
            # 有多个事件，可能有档位变更
            changes = []
            for i in range(1, len(recent_events)):
                if recent_events[i].level != recent_events[i-1].level:
                    changes.append({
                        "from": recent_events[i-1].level.value,
                        "to": recent_events[i].level.value,
                        "date": recent_events[i].event_date.isoformat(),
                        "title": recent_events[i].title
                    })

            if changes:
                _send_transition_summary(changes)

        logger.info("Policy transition monitoring completed")

        return {
            "status": "success",
            "events_checked": len(recent_events),
            "transitions_found": len(changes) if len(recent_events) > 1 else 0
        }

    except Exception as e:
        logger.error(f"Policy transition monitoring failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@shared_task
def cleanup_old_policy_logs(days_to_keep: int = 365):
    """
    清理旧的政策日志

    保留指定天数内的日志，删除更早的日志

    Args:
        days_to_keep: 保留天数（默认 365 天）
    """
    try:
        from ..infrastructure.models import PolicyLog
        from django.utils import timezone

        cutoff_date = date.today() - timedelta(days=days_to_keep)

        deleted_count = PolicyLog.objects.filter(
            event_date__lt=cutoff_date
        ).delete()[0]

        logger.info(f"Cleaned up {deleted_count} old policy logs")

        return {
            "status": "success",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Policy log cleanup failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@shared_task
def generate_daily_policy_summary():
    """
    生成每日政策摘要

    汇总当天的政策状态，供日报使用
    """
    try:
        repo = DjangoPolicyRepository()
        use_case = GetPolicyStatusUseCase(event_store=repo)

        status = use_case.execute(date.today())

        summary = {
            "date": date.today().isoformat(),
            "current_level": status.current_level.value,
            "level_name": status.level_name,
            "is_intervention_active": status.is_intervention_active,
            "is_crisis_mode": status.is_crisis_mode,
            "latest_event": None,
            "recommendations": status.recommendations
        }

        if status.latest_event:
            summary["latest_event"] = {
                "date": status.latest_event.event_date.isoformat(),
                "level": status.latest_event.level.value,
                "title": status.latest_event.title,
                "description": status.latest_event.description,
                "evidence_url": status.latest_event.evidence_url
            }

        # 存储摘要（可选：发送到缓存或数据库）
        logger.info(f"Daily policy summary generated: {summary['current_level']}")

        return summary

    except Exception as e:
        logger.error(f"Daily policy summary generation failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


# 辅助函数

def _send_policy_alert(
    level: PolicyLevel,
    event: PolicyEvent,
    status: Any
):
    """
    发送政策告警

    Args:
        level: 政策档位
        event: 政策事件
        status: 政策状态
    """
    try:
        # 这里可以集成具体的告警服务
        # 例如：Slack webhook、邮件、短信等

        alert_level = "critical" if level == PolicyLevel.P3 else "warning"

        message = f"""
**政策状态告警**

档位: {level.value} - {status.level_name}
标题: {event.title}
描述: {event.description}
日期: {event.event_date}

**响应措施**:
- 现金调整: +{status.response_config.cash_adjustment}%
- 行动: {status.response_config.market_action.value}
"""

        if status.response_config.signal_pause_hours:
            message += f"- 信号暂停: {status.response_config.signal_pause_hours} 小时\n"

        message += f"""
**建议**:
{chr(10).join(f'- {r}' for r in status.recommendations)}

证据: {event.evidence_url}
        """

        # TODO: 实际发送告警
        # - Slack: send_slack_message(alert_level, message)
        # - Email: send_email(alert_level, message)
        # - SMS: send_sms(alert_level, message)

        logger.warning(f"Policy alert would be sent: {alert_level} - {level.value}")

    except Exception as e:
        logger.error(f"Failed to send policy alert: {e}")


def _send_transition_summary(changes: list):
    """
    发送档位变更摘要

    Args:
        changes: 变更列表
    """
    try:
        message = "**政策档位变更摘要**\n\n"

        for change in changes:
            message += f"""
- {change['date']}: {change['from']} → {change['to']}
  标题: {change['title']}
"""

        # TODO: 实际发送
        logger.warning(f"Policy transition summary: {len(changes)} changes")

    except Exception as e:
        logger.error(f"Failed to send transition summary: {e}")


# ========== RSS 相关任务 ==========

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def fetch_rss_sources(self, source_id: Optional[int] = None):
    """
    定时抓取RSS源（增强版 - 集成AI分类）

    该任务应由Celery Beat定时调用（如每6小时一次）

    Args:
        source_id: 指定源ID，None表示抓取所有启用的源
    """
    from .use_cases import FetchRSSUseCase, FetchRSSInput
    from ..infrastructure.repositories import RSSRepository
    from ..infrastructure.adapters.ai_policy_classifier import create_ai_policy_classifier

    try:
        rss_repo = RSSRepository()
        policy_repo = DjangoPolicyRepository()

        # 创建AI分类器（如果配置了AI服务）
        try:
            ai_classifier = create_ai_policy_classifier()
            if ai_classifier:
                logger.info("AI classifier initialized successfully")
            else:
                logger.info("AI classifier not available, will use keyword matching only")
        except Exception as e:
            logger.warning(f"Failed to initialize AI classifier: {e}. Will use keyword matching only.")
            ai_classifier = None

        use_case = FetchRSSUseCase(
            rss_repository=rss_repo,
            policy_repository=policy_repo,
            ai_classifier=ai_classifier
        )

        input_dto = FetchRSSInput(source_id=source_id)
        output = use_case.execute(input_dto)

        logger.info(
            f"RSS fetch completed: {output.sources_processed} sources, "
            f"{output.new_policy_events} new events"
        )

        # 统计各分类数量
        if output.new_policy_events > 0:
            from ..infrastructure.models import PolicyLog
            category_stats = PolicyLog.objects.aggregate(
                macro=Count('id', filter=Q(info_category='macro')),
                sector=Count('id', filter=Q(info_category='sector')),
                individual=Count('id', filter=Q(info_category='individual')),
                sentiment=Count('id', filter=Q(info_category='sentiment')),
                other=Count('id', filter=Q(info_category='other'))
            )
            logger.info(f"Policy categories: {category_stats}")

        return {
            "status": "success",
            "sources_processed": output.sources_processed,
            "total_items": output.total_items,
            "new_events": output.new_policy_events,
            "errors": output.errors
        }

    except Exception as e:
        logger.error(f"RSS fetch failed: {e}", exc_info=True)
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for RSS fetch")
            raise


@shared_task
def cleanup_old_rss_logs(days_to_keep: int = 90):
    """
    清理旧的RSS抓取日志

    Args:
        days_to_keep: 保留天数
    """
    try:
        from ..infrastructure.repositories import RSSRepository

        rss_repo = RSSRepository()
        deleted_count = rss_repo.cleanup_old_logs(days_to_keep)

        logger.info(f"Cleaned up {deleted_count} old RSS logs")

        return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"RSS log cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


# ========== 审核相关任务 ==========

@shared_task
def auto_assign_pending_audits(max_per_user: int = 10):
    """
    自动分配待审核的政策

    该任务应由Celery Beat定时调用（如每小时一次）

    Args:
        max_per_user: 每个用户最多分配数量
    """
    try:
        from ..infrastructure.models import PolicyAuditQueue
        from django.contrib.auth.models import User
        from django.utils import timezone

        # 获取所有待审核且未分配的政策
        unassigned = PolicyAuditQueue.objects.filter(
            assigned_to__isnull=True,
            policy_log__audit_status='pending_review'
        ).order_by('-created_at')

        # 获取可用的审核人员（有审核权限的用户）
        # 简化版本：获取所有员工用户
        auditors = User.objects.filter(is_staff=True).distinct()

        if not auditors:
            logger.warning("No auditors found with staff privileges")
            return {'assigned': 0, 'remaining': unassigned.count()}

        # 轮询分配
        assigned_count = 0
        for idx, queue_item in enumerate(unassigned):
            auditor = auditors[idx % auditors.count()]

            # 检查该用户已分配数量
            current_assigned = PolicyAuditQueue.objects.filter(
                assigned_to=auditor,
                policy_log__audit_status='pending_review'
            ).count()

            if current_assigned >= max_per_user:
                continue

            queue_item.assigned_to = auditor
            queue_item.assigned_at = timezone.now()
            queue_item.save()

            assigned_count += 1

        logger.info(
            f"Auto-assigned {assigned_count} policy reviews to {auditors.count()} auditors"
        )

        return {
            'assigned': assigned_count,
            'remaining': unassigned.count() - assigned_count,
            'auditors': auditors.count()
        }

    except Exception as e:
        logger.error(f"Auto-assign audits failed: {e}", exc_info=True)
        return {
            'assigned': 0,
            'error': str(e)
        }


@shared_task
def cleanup_old_audit_queues(days_to_keep: int = 30):
    """
    清理旧的审核队列记录

    删除已审核超过指定天数的队列记录

    Args:
        days_to_keep: 保留天数
    """
    try:
        from ..infrastructure.models import PolicyAuditQueue
        from django.utils import timezone

        cutoff_date = timezone.now() - timedelta(days=days_to_keep)

        # 只删除已审核的队列记录
        deleted_count = PolicyAuditQueue.objects.filter(
            policy_log__reviewed_at__lt=cutoff_date
        ).delete()[0]

        logger.info(f"Cleaned up {deleted_count} old audit queue records")

        return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"Audit queue cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


@shared_task
def generate_daily_policy_summary():
    """
    生成每日政策摘要（增强版）

    汇总当天的政策状态，包括AI分类统计
    """
    try:
        from ..infrastructure.models import PolicyLog, PolicyAuditQueue
        from django.utils import timezone

        today = timezone.now().date()

        # 今日新增政策统计
        today_policies = PolicyLog.objects.filter(created_at__date=today)

        summary = {
            "date": today.isoformat(),
            "total_new": today_policies.count(),
            "by_level": {},
            "by_category": {},
            "by_audit_status": {},
            "pending_review": PolicyAuditQueue.objects.filter(
                policy_log__audit_status='pending_review'
            ).count(),
            "ai_classified": today_policies.filter(
                Q(audit_status='auto_approved') | Q(audit_status='pending_review'),
                ai_confidence__isnull=False
            ).count(),
        }

        # 按档位统计
        for level_code, level_name in PolicyLog.POLICY_LEVELS:
            count = today_policies.filter(level=level_code).count()
            if count > 0:
                summary["by_level"][level_name] = count

        # 按分类统计
        for cat_code, cat_name in PolicyLog.INFO_CATEGORY_CHOICES:
            count = today_policies.filter(info_category=cat_code).count()
            if count > 0:
                summary["by_category"][cat_name] = count

        # 按审核状态统计
        for status_code, status_name in PolicyLog.AUDIT_STATUS_CHOICES:
            count = today_policies.filter(audit_status=status_code).count()
            if count > 0:
                summary["by_audit_status"][status_name] = count

        # 存储摘要或发送告警
        logger.info(f"Daily policy summary generated: {summary}")

        return summary

    except Exception as e:
        logger.error(f"Daily policy summary generation failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


# ========== Signal 同步相关任务 ==========

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True
)
def trigger_signal_reevaluation(
    self,
    new_level: int,
    event_date: str
) -> dict:
    """
    重评所有活跃信号任务

    当政策档位变化时，重新评估所有活跃信号是否应该被拒绝。

    Args:
        new_level: 新的政策档位（0-3）
        event_date: 事件日期

    Returns:
        dict: 重评结果
    """
    try:
        from apps.signal.infrastructure.repositories import DjangoSignalRepository
        from apps.signal.application.use_cases import ReevaluateSignalsUseCase, ReevaluateSignalsRequest
        from apps.regime.infrastructure.repositories import DjangoRegimeRepository

        logger.info(
            f"Starting signal reevaluation for policy level P{new_level}, "
            f"event_date={event_date}"
        )

        # 获取当前 Regime（如果可用）
        regime_repo = DjangoRegimeRepository()
        latest_regime = regime_repo.get_latest_snapshot()

        current_regime = latest_regime.dominant_regime if latest_regime else None
        regime_confidence = latest_regime.confidence if latest_regime else 0.0

        # 创建仓储和用例
        signal_repo = DjangoSignalRepository()
        use_case = ReevaluateSignalsUseCase(signal_repository=signal_repo)

        # 执行重评
        request = ReevaluateSignalsRequest(
            policy_level=new_level,
            current_regime=current_regime,
            regime_confidence=regime_confidence
        )

        result = use_case.execute(request)

        logger.info(
            f"Signal reevaluation completed: {result.rejected_count}/{result.total_count} "
            f"signals rejected"
        )

        return {
            'status': 'success',
            'total_count': result.total_count,
            'rejected_count': result.rejected_count,
            'rejected_signal_ids': result.rejected_signal_ids,
            'policy_level': f'P{new_level}',
            'event_date': event_date,
            'current_regime': current_regime
        }

    except Exception as exc:
        logger.error(f"Signal reevaluation failed: {exc}", exc_info=True)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {
                'status': 'error',
                'error': str(exc)
            }
