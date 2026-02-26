"""
Celery Tasks for Signal Management

定期执行信号证伪检查等后台任务
"""

from celery import shared_task
from django.utils import timezone
from django.conf import settings
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
    from django.contrib.auth import get_user_model

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

    # 获取新建的信号详情
    new_signal_details = list(InvestmentSignalModel._default_manager.filter(
        created_at__range=[yesterday, today]
    ).values('asset_code', 'logic_desc', 'created_by')[:10])

    # 获取证伪的信号详情
    invalidated_details = list(InvestmentSignalModel._default_manager.filter(
        invalidated_at__range=[yesterday, today]
    ).values('asset_code', 'logic_desc', 'invalidated_reason', 'id')[:10])

    summary = {
        'date': yesterday.date().isoformat(),
        'new_signals': new_signals,
        'invalidated_signals': invalidated_signals,
        'total_approved': approved_count
    }

    logger.info(f"每日信号摘要: {summary}")

    # 发送通知
    _send_signal_summary_notification(summary, new_signal_details, invalidated_details)

    return summary


def _send_signal_summary_notification(summary: dict, new_details: list, invalidated_details: list) -> bool:
    """
    发送信号摘要通知

    Args:
        summary: 摘要统计数据
        new_details: 新建信号详情
        invalidated_details: 证伪信号详情

    Returns:
        bool: 是否发送成功
    """
    from shared.infrastructure.notification_service import (
        get_notification_service,
        NotificationMessage,
        NotificationPriority,
    )
    from django.core.mail import send_mail
    from django.conf import settings

    service = get_notification_service()

    # 构建邮件内容
    subject = f"[AgomSAAF] 每日信号摘要 - {summary['date']}"

    lines = [
        f"# 每日信号状态摘要",
        f"**日期**: {summary['date']}",
        f"",
        f"## 统计数据",
        f"- 新建信号: {summary['new_signals']} 个",
        f"- 证伪信号: {summary['invalidated_signals']} 个",
        f"- 当前有效信号: {summary['total_approved']} 个",
        f"",
    ]

    # 添加新建信号详情
    if new_details:
        lines.extend([
            f"## 新建信号 ({len(new_details)})",
            f"",
        ])
        for i, signal in enumerate(new_details[:10], 1):
            lines.append(f"{i}. **{signal['asset_code']}** - {signal.get('logic_desc', 'N/A')}")
        if len(new_details) > 10:
            lines.append(f"... 还有 {len(new_details) - 10} 个信号")
        lines.append("")

    # 添加证伪信号详情
    if invalidated_details:
        lines.extend([
            f"## 证伪信号 ({len(invalidated_details)})",
            f"",
        ])
        for i, signal in enumerate(invalidated_details[:10], 1):
            reason = signal.get('invalidated_reason', 'N/A')
            lines.append(f"{i}. **{signal['asset_code']}** (ID: {signal['id']}) - {reason}")
        if len(invalidated_details) > 10:
            lines.append(f"... 还有 {len(invalidated_details) - 10} 个信号")
        lines.append("")

    lines.extend([
        "---",
        f"发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ])

    body = "\n".join(lines)

    # 构建 HTML 邮件内容
    html_body = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .header {{ background-color: #007bff; color: white; padding: 20px; text-align: center; }}
            .section {{ margin: 20px 0; padding: 15px; background-color: #f8f9fa; border-radius: 5px; }}
            .stat {{ display: inline-block; margin: 10px 20px; padding: 10px; background-color: white; border-radius: 5px; }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: #007bff; }}
            .stat-label {{ font-size: 12px; color: #6c757d; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #007bff; color: white; }}
            .footer {{ background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>每日信号状态摘要</h2>
            <p>{summary['date']}</p>
        </div>

        <div class="section">
            <h3>统计数据</h3>
            <div class="stat">
                <div class="stat-value">{summary['new_signals']}</div>
                <div class="stat-label">新建信号</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary['invalidated_signals']}</div>
                <div class="stat-label">证伪信号</div>
            </div>
            <div class="stat">
                <div class="stat-value">{summary['total_approved']}</div>
                <div class="stat-label">当前有效</div>
            </div>
        </div>
    """

    if new_details:
        html_body += """
        <div class="section">
            <h3>新建信号</h3>
            <table>
                <tr><th>序号</th><th>资产代码</th><th>逻辑描述</th></tr>
        """
        for i, signal in enumerate(new_details[:10], 1):
            html_body += f"<tr><td>{i}</td><td>{signal['asset_code']}</td><td>{signal.get('logic_desc', 'N/A')}</td></tr>"
        html_body += "</table></div>"

    if invalidated_details:
        html_body += """
        <div class="section">
            <h3>证伪信号</h3>
            <table>
                <tr><th>序号</th><th>资产代码</th><th>证伪原因</th></tr>
        """
        for i, signal in enumerate(invalidated_details[:10], 1):
            reason = signal.get('invalidated_reason', 'N/A')
            html_body += f"<tr><td>{i}</td><td>{signal['asset_code']}</td><td>{reason}</td></tr>"
        html_body += "</table></div>"

    html_body += f"""
        <div class="footer">
            <p>发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>AgomSaaS - 自动发送，请勿回复</p>
        </div>
    </body>
    </html>
    """

    # 获取收件人列表
    recipients = _get_signal_notification_recipients()

    if recipients:
        try:
            # 使用统一通知服务发送邮件
            result = service.send_email(
                subject=subject,
                body=body,
                recipients=recipients,
                html_body=html_body,
                priority=NotificationPriority.NORMAL,
            )

            success = any(r.success for r in result)
            if success:
                logger.info(f"信号摘要通知已发送: recipients={len(recipients)}")
            else:
                logger.warning("信号摘要通知发送失败")

            return success

        except Exception as e:
            logger.error(f"发送信号摘要通知失败: {e}", exc_info=True)
            return False
    else:
        logger.info("没有配置信号通知收件人，跳过发送")
        return True


def _get_signal_notification_recipients() -> list:
    """
    获取信号通知收件人列表

    Returns:
        list: 收件人邮箱列表
    """
    from django.contrib.auth import get_user_model
    from django.conf import settings

    User = get_user_model()
    recipients = []

    # 从配置获取
    config_emails = getattr(settings, 'SIGNAL_NOTIFICATION_EMAILS', [])
    if config_emails:
        recipients.extend(config_emails)

    # 获取管理员邮箱
    admin_emails = list(User.objects.filter(
        is_staff=True,
        is_active=True,
        email__icontains='@'
    ).exclude(
        email=''
    ).values_list('email', flat=True))

    recipients.extend(admin_emails)

    # 去重并过滤空值
    recipients = list(set(r for r in recipients if r and '@' in r))

    return recipients

