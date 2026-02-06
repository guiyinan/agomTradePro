"""
Celery Tasks for Signal Management

定期执行信号证伪检查等后台任务
"""

from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


@shared_task(name='signal.check_all_invalidations')
def check_all_signal_invalidations():
    """
    定期检查所有已批准信号是否满足证伪条件

    建议每天运行一次，比如凌晨 2:00
    """
    from apps.signal.application.invalidation_checker import check_and_invalidate_signals

    logger.info(f"[{timezone.now()}] 开始检查信号证伪状态...")

    try:
        result = check_and_invalidate_signals()

        logger.info(
            f"检查完成: 共检查 {result['checked']} 个信号, "
            f"证伪 {result['invalidated']} 个, "
            f"证伪信号 IDs: {result['signal_ids']}"
        )

        return result

    except Exception as e:
        logger.error(f"信号证伪检查失败: {e}", exc_info=True)
        raise


@shared_task(name='signal.check_single_invalidation')
def check_single_signal_invalidation(signal_id: int):
    """
    检查单个信号的证伪状态

    用于手动触发或信号状态变化时检查
    """
    from apps.signal.application.invalidation_checker import InvalidationCheckService

    logger.info(f"检查信号 {signal_id} 的证伪状态...")

    try:
        service = InvalidationCheckService()
        result = service.check_signal(signal_id)

        if result:
            if result.is_invalidated:
                logger.info(f"信号 {signal_id} 已被证伪: {result.reason}")
            else:
                logger.info(f"信号 {signal_id} 未满足证伪条件: {result.reason}")

            return {
                'signal_id': signal_id,
                'is_invalidated': result.is_invalidated,
                'reason': result.reason
            }
        else:
            logger.warning(f"信号 {signal_id} 不存在")
            return None

    except Exception as e:
        logger.error(f"检查信号 {signal_id} 失败: {e}", exc_info=True)
        raise


@shared_task(name='signal.cleanup_old_invalidated')
def cleanup_old_invalidated_signals(days: int = 90):
    """
    清理旧的已证伪信号

    默认清理 90 天前的证伪信号，可以归档或删除
    """
    from apps.signal.infrastructure.models import InvestmentSignalModel
    from datetime import timedelta

    cutoff_date = timezone.now() - timedelta(days=days)

    logger.info(f"清理 {days} 天前的已证伪信号...")

    try:
        old_signals = InvestmentSignalModel._default_manager.filter(
            status='invalidated',
            invalidated_at__lt=cutoff_date
        )

        count = old_signals.count()
        old_ids = list(old_signals.values_list('id', flat=True))

        # 这里可以选择删除或归档
        # old_signals.delete()

        logger.info(f"找到 {count} 个旧证伪信号: {old_ids}")

        return {
            'found': count,
            'signal_ids': old_ids
        }

    except Exception as e:
        logger.error(f"清理旧证伪信号失败: {e}", exc_info=True)
        raise


@shared_task(name='signal.daily_summary')
def send_daily_signal_summary():
    """
    发送每日信号状态摘要

    每天早上发送前一天的状态变化报告
    """
    from apps.signal.infrastructure.models import InvestmentSignalModel
    from datetime import timedelta

    yesterday = timezone.now() - timedelta(days=1)
    today = timezone.now()

    # 统计变化
    new_signals = InvestmentSignalModel._default_manager.filter(
        created_at__range=[yesterday, today]
    ).count()

    invalidated_signals = InvestmentSignalModel._default_manager.filter(
        invalidated_at__range=[yesterday, today]
    ).count()

    approved_count = InvestmentSignalModel._default_manager.filter(
        status='approved'
    ).count()

    summary = {
        'date': yesterday.date().isoformat(),
        'new_signals': new_signals,
        'invalidated_signals': invalidated_signals,
        'total_approved': approved_count
    }

    logger.info(f"每日信号摘要: {summary}")

    # TODO: 发送邮件或钉钉通知

    return summary

