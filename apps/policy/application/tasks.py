"""
Application Layer - Celery Tasks for Policy Management

定义异步任务，如定时检查、告警发送等。
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.db import DatabaseError, IntegrityError
from django.utils import timezone

from core.exceptions import (
    BusinessLogicError,
    DataFetchError,
    ExternalServiceError,
)
from core.metrics import record_exception

from ..domain.entities import PolicyEvent, PolicyLevel
from .repository_provider import (
    get_ai_policy_classifier,
    get_current_policy_repository,
    get_policy_notification_service,
    get_rss_repository,
    get_workbench_repository,
)
from .use_cases import GetPolicyStatusUseCase

logger = logging.getLogger(__name__)

# 获取通知服务实例（通过工厂单例）
_notification_service = None


def _get_notification_service():
    """获取通知服务实例（延迟初始化）"""
    global _notification_service
    if _notification_service is None:
        _notification_service = get_policy_notification_service()
    return _notification_service


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5分钟后重试
    time_limit=600,
    soft_time_limit=570,
)
def check_policy_status_alert(self, as_of_date_str: str | None = None):
    """
    定时检查政策状态并发送告警（如需要）

    该任务应由 Celery Beat 定时调用（如每小时一次）

    Args:
        as_of_date_str: 日期字符串 (YYYY-MM-DD)，None 表示今天
    """
    try:
        as_of_date = date.fromisoformat(as_of_date_str) if as_of_date_str else date.today()

        repo = get_current_policy_repository()
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

    except (DataFetchError, ExternalServiceError) as e:
        # Retryable external errors
        logger.warning(f"Policy status check failed (retryable): {e}")
        record_exception(e, module="policy", is_handled=True, service_name="policy_check")
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for policy status check")
            record_exception(e, module="policy", is_handled=True, service_name="policy_check")
            raise
    except (BusinessLogicError, ValueError) as e:
        # Non-retryable business logic errors
        logger.error(f"Policy status check failed (non-retryable): {e}")
        record_exception(e, module="policy", is_handled=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": "business_logic"
        }
    except Exception as e:
        # Unexpected error - still retry but log differently
        logger.exception(f"Policy status check failed (unexpected): {e}")
        record_exception(e, module="policy", is_handled=False)
        try:
            raise self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for policy status check")
            raise


@shared_task(time_limit=600, soft_time_limit=570)
def monitor_policy_transitions():
    """
    监控政策档位变更

    检查最近 24 小时内是否有档位变更，如有则发送摘要
    """
    try:
        repo = get_current_policy_repository()

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

    except (DataFetchError, DatabaseError) as e:
        logger.warning(f"Policy transition monitoring failed (data error): {e}")
        record_exception(e, module="policy", is_handled=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": "data_fetch"
        }
    except Exception as e:
        logger.exception(f"Policy transition monitoring failed (unexpected): {e}")
        record_exception(e, module="policy", is_handled=False)
        return {
            "status": "error",
            "error": str(e)
        }


@shared_task(time_limit=600, soft_time_limit=570)
def cleanup_old_policy_logs(days_to_keep: int = 365):
    """
    清理旧的政策日志

    保留指定天数内的日志，删除更早的日志

    Args:
        days_to_keep: 保留天数（默认 365 天）
    """
    try:
        cutoff_date = date.today() - timedelta(days=days_to_keep)

        deleted_count = get_current_policy_repository().delete_events_before(cutoff_date)

        logger.info(f"Cleaned up {deleted_count} old policy logs")

        return {
            "status": "success",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat()
        }

    except DatabaseError as e:
        logger.error(f"Policy log cleanup failed (database error): {e}", exc_info=True)
        record_exception(e, module="policy", is_handled=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": "database"
        }
    except Exception as e:
        logger.exception(f"Policy log cleanup failed (unexpected): {e}")
        record_exception(e, module="policy", is_handled=False)
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
        # 使用通知服务发送告警
        alert_service = _get_notification_service()
        alert_service.send_policy_alert(level, event, status)

        alert_level = "critical" if level == PolicyLevel.P3 else "warning"
        logger.info(f"Policy alert sent: {alert_level} - {level.value}")

    except Exception as e:
        logger.error(f"Failed to send policy alert: {e}", exc_info=True)


def _send_transition_summary(changes: list):
    """
    发送档位变更摘要

    Args:
        changes: 变更列表
    """
    try:
        # 使用通知服务发送摘要
        alert_service = _get_notification_service()
        alert_service.send_transition_summary(changes)

        logger.info(f"Policy transition summary sent: {len(changes)} changes")

    except Exception as e:
        logger.error(f"Failed to send transition summary: {e}", exc_info=True)


# ========== RSS 相关任务 ==========

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    time_limit=600,
    soft_time_limit=570,
)
def fetch_rss_sources(self, source_id: int | None = None):
    """
    定时抓取RSS源（增强版 - 集成AI分类）

    该任务应由Celery Beat定时调用（如每6小时一次）

    Args:
        source_id: 指定源ID，None表示抓取所有启用的源
    """
    from .use_cases import FetchRSSInput, FetchRSSUseCase

    try:
        rss_repo = get_rss_repository()
        policy_repo = get_current_policy_repository()

        # 创建AI分类器（如果配置了AI服务）
        try:
            ai_classifier = get_ai_policy_classifier()
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
            category_stats = policy_repo.get_category_stats()
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


@shared_task(time_limit=600, soft_time_limit=570)
def cleanup_old_rss_logs(days_to_keep: int = 90):
    """
    清理旧的RSS抓取日志

    Args:
        days_to_keep: 保留天数
    """
    try:
        rss_repo = get_rss_repository()
        deleted_count = rss_repo.cleanup_old_logs(days_to_keep)

        logger.info(f"Cleaned up {deleted_count} old RSS logs")

        return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"RSS log cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


# ========== 审核相关任务 ==========

@shared_task(time_limit=600, soft_time_limit=570)
def auto_assign_pending_audits(max_per_user: int = 10):
    """
    自动分配待审核的政策

    该任务应由Celery Beat定时调用（如每小时一次）

    Args:
        max_per_user: 每个用户最多分配数量
    """
    try:
        workbench_repo = get_workbench_repository()

        # 获取所有待审核且未分配的政策
        unassigned_ids = workbench_repo.list_unassigned_audit_queue_ids()

        # 获取可用的审核人员（有审核权限的用户）
        auditor_ids = workbench_repo.list_staff_auditor_ids()

        if not auditor_ids:
            logger.warning("No auditors found with staff privileges")
            return {'assigned': 0, 'remaining': len(unassigned_ids)}

        # 轮询分配
        assigned_per_auditor = workbench_repo.get_pending_assignment_counts(auditor_ids)
        assigned_count = 0
        auditor_count = len(auditor_ids)
        assignment_time = timezone.now()
        for idx, queue_id in enumerate(unassigned_ids):
            for offset in range(auditor_count):
                auditor_id = auditor_ids[(idx + offset) % auditor_count]
                current_assigned = assigned_per_auditor.get(auditor_id, 0)

                if current_assigned >= max_per_user:
                    continue

                if workbench_repo.assign_audit_queue_item(
                    queue_id=queue_id,
                    auditor_id=auditor_id,
                    assigned_at=assignment_time,
                ):
                    assigned_per_auditor[auditor_id] = current_assigned + 1
                    assigned_count += 1
                    break

        logger.info(
            f"Auto-assigned {assigned_count} policy reviews to {auditor_count} auditors"
        )

        return {
            'assigned': assigned_count,
            'remaining': len(unassigned_ids) - assigned_count,
            'auditors': auditor_count
        }

    except Exception as e:
        logger.error(f"Auto-assign audits failed: {e}", exc_info=True)
        return {
            'assigned': 0,
            'error': str(e)
        }


@shared_task(time_limit=600, soft_time_limit=570)
def cleanup_old_audit_queues(days_to_keep: int = 30):
    """
    清理旧的审核队列记录

    删除已审核超过指定天数的队列记录

    Args:
        days_to_keep: 保留天数
    """
    try:
        cutoff_date = timezone.now() - timedelta(days=days_to_keep)

        # 只删除已审核的队列记录
        deleted_count = get_workbench_repository().delete_reviewed_queue_before(cutoff_date)

        logger.info(f"Cleaned up {deleted_count} old audit queue records")

        return {"status": "success", "deleted_count": deleted_count}

    except Exception as e:
        logger.error(f"Audit queue cleanup failed: {e}")
        return {"status": "error", "error": str(e)}


@shared_task(time_limit=600, soft_time_limit=570)
def generate_daily_policy_summary():
    """
    生成每日政策摘要（增强版）

    汇总当天的政策状态，包括AI分类统计
    """
    try:
        today = timezone.now().date()
        summary = get_workbench_repository().get_daily_policy_summary(today)

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
    retry_backoff=True,
    time_limit=600,
    soft_time_limit=570,
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
        from apps.regime.application.current_regime import resolve_current_regime
        from apps.signal.application.use_cases import (
            ReevaluateSignalsRequest,
            ReevaluateSignalsUseCase,
        )
        from apps.signal.application.repository_provider import get_signal_repository

        logger.info(
            f"Starting signal reevaluation for policy level P{new_level}, "
            f"event_date={event_date}"
        )

        # 获取当前 Regime（如果可用）
        latest_regime = resolve_current_regime()
        current_regime = latest_regime.dominant_regime
        regime_confidence = latest_regime.confidence

        # 创建仓储和用例
        signal_repo = get_signal_repository()
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


# ========== 工作台相关任务 ==========

@shared_task(time_limit=600, soft_time_limit=570)
def auto_assign_pending_audits_task(max_per_user: int = 10):
    """
    自动分配待审核的政策

    该任务应由 Celery Beat 定时调用（如每 15 分钟一次）

    Args:
        max_per_user: 每个用户最多分配数量
    """
    return auto_assign_pending_audits(max_per_user)


@shared_task(time_limit=600, soft_time_limit=570)
def monitor_sla_exceeded_task():
    """
    监控 SLA 超时事件

    该任务应由 Celery Beat 定时调用（如每 10 分钟一次）
    """
    try:
        workbench_repo = get_workbench_repository()
        config = workbench_repo.get_ingestion_config()
        breakdown = workbench_repo.get_sla_exceeded_breakdown(
            p23_sla_hours=config.p23_sla_hours,
            normal_sla_hours=config.normal_sla_hours,
        )
        total_exceeded = breakdown["total_exceeded"]

        if total_exceeded > 0:
            logger.warning(
                f"SLA exceeded: {breakdown['p23_exceeded']} P2/P3, "
                f"{breakdown['normal_exceeded']} P0/P1"
            )
            # 使用通知服务发送SLA告警
            alert_service = _get_notification_service()
            alert_service.send_sla_alert(
                breakdown["p23_exceeded"],
                breakdown["normal_exceeded"],
            )

        return {
            "status": "success",
            "p23_exceeded": breakdown["p23_exceeded"],
            "normal_exceeded": breakdown["normal_exceeded"],
            "total_exceeded": total_exceeded,
        }

    except Exception as e:
        logger.error(f"SLA monitor failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@shared_task(time_limit=600, soft_time_limit=570)
def refresh_gate_constraints_task():
    """
    刷新闸门约束

    该任务应由 Celery Beat 定时调用（如每 5 分钟一次）
    """
    try:
        from ..domain.rules import calculate_gate_level

        workbench_repo = get_workbench_repository()

        # 获取全局热度与情绪
        global_heat, global_sentiment = workbench_repo.get_global_heat_sentiment()

        # 获取闸门配置
        gate_config = workbench_repo.get_gate_config('all')

        if gate_config and global_heat is not None:
            from ..domain.entities import SentimentGateThresholds

            thresholds = SentimentGateThresholds(
                heat_l1_threshold=gate_config.heat_l1_threshold,
                heat_l2_threshold=gate_config.heat_l2_threshold,
                heat_l3_threshold=gate_config.heat_l3_threshold,
                sentiment_l1_threshold=gate_config.sentiment_l1_threshold,
                sentiment_l2_threshold=gate_config.sentiment_l2_threshold,
                sentiment_l3_threshold=gate_config.sentiment_l3_threshold,
            )

            gate_level = calculate_gate_level(global_heat, global_sentiment, thresholds)

            logger.info(
                f"Gate constraints refreshed: heat={global_heat:.1f}, "
                f"sentiment={global_sentiment:.2f}, level={gate_level.value}"
            )

            return {
                "status": "success",
                "heat_score": global_heat,
                "sentiment_score": global_sentiment,
                "gate_level": gate_level.value,
            }

        return {
            "status": "success",
            "message": "No gate config or data available"
        }

    except Exception as e:
        logger.error(f"Gate constraints refresh failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }
