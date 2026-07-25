"""
Celery Tasks for Signal Management

定期执行信号证伪检查等后台任务
"""

import html
import logging
from collections.abc import Iterable, Mapping
from itertools import chain
from typing import Any, TypedDict, cast

from celery.exceptions import MaxRetriesExceededError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import DatabaseError
from django.utils import timezone

from apps.signal.application.repository_provider import (
    get_signal_repository,
    get_user_repository,
)
from core.exceptions import BusinessLogicError, DataFetchError
from core.integration.research_integrity_registry import (
    record_forecast_evaluation_for_signal,
)
from core.metrics import record_exception
from shared.infrastructure.celery_typing import BoundTask, typed_shared_task

logger = logging.getLogger(__name__)

_MAX_CLEANUP_DAYS = 3650
_MAX_NOTIFICATION_RECIPIENTS = 100
_MAX_DETAIL_TEXT_LENGTH = 500


class SignalSummary(TypedDict):
    """Daily signal summary returned by the scheduled task."""

    date: str
    new_signals: int
    invalidated_signals: int
    total_approved: int
    notification_sent: bool


def _validated_batch_result(result: object) -> dict[str, object]:
    """Validate invalidation batch evidence before publishing task success."""

    if not isinstance(result, Mapping):
        raise BusinessLogicError("Signal invalidation returned an invalid result")
    normalized: dict[str, object] = dict(result)
    for field_name in ("checked", "invalidated", "rejected"):
        value = normalized.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BusinessLogicError("Signal invalidation returned invalid counters")
    for field_name in ("invalidated_ids", "rejected_ids"):
        value = normalized.get(field_name)
        if not isinstance(value, list) or any(
            isinstance(item, bool) or not isinstance(item, (int, str)) or not str(item).strip()
            for item in value
        ):
            raise BusinessLogicError("Signal invalidation returned invalid identifiers")
    if normalized["invalidated"] != len(cast(list[object], normalized["invalidated_ids"])):
        raise BusinessLogicError("Signal invalidation count does not match its identifiers")
    if normalized["rejected"] != len(cast(list[object], normalized["rejected_ids"])):
        raise BusinessLogicError("Signal rejection count does not match its identifiers")
    if cast(int, normalized["checked"]) < (
        cast(int, normalized["invalidated"]) + cast(int, normalized["rejected"])
    ):
        raise BusinessLogicError("Signal invalidation counters are inconsistent")
    return normalized


@typed_shared_task(
    name="signal.check_all_invalidations",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=600,
    soft_time_limit=570,
)
def check_all_signal_invalidations(self: BoundTask) -> dict[str, object]:
    """
    定期检查所有已批准信号是否满足证伪条件

    建议每天运行一次，比如凌晨 2:00
    """
    from apps.signal.application.invalidation_checker import check_and_invalidate_signals

    logger.info(f"[{timezone.now()}] 开始检查信号证伪状态...")

    try:
        result = _validated_batch_result(check_and_invalidate_signals())

        logger.info(
            f"检查完成: 共检查 {result['checked']} 个信号, "
            f"证伪 {result['invalidated']} 个, 拒绝 {result['rejected']} 个, "
            f"证伪信号 IDs: {result['invalidated_ids']}, "
            f"拒绝信号 IDs: {result['rejected_ids']}"
        )

        return result

    except (DataFetchError, DatabaseError) as exc:
        # Retryable data errors
        logger.warning("信号证伪检查失败（数据错误）: %s", exc)
        record_exception(exc, module="signal", is_handled=True)
        try:
            raise self.retry(exc=exc, countdown=300)
        except MaxRetriesExceededError:
            logger.error("Max retries exceeded for signal invalidation check")
            raise
    except BusinessLogicError as exc:
        # Non-retryable business logic errors
        logger.error("信号证伪检查失败（业务逻辑）: %s", exc)
        record_exception(exc, module="signal", is_handled=True)
        raise
    except Exception as exc:
        logger.exception("信号证伪检查失败（未预期）")
        record_exception(exc, module="signal", is_handled=False)
        raise


@typed_shared_task(
    name="signal.check_single_invalidation",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=600,
    soft_time_limit=570,
)
def check_single_signal_invalidation(
    self: BoundTask,
    signal_id: int,
) -> dict[str, object] | None:
    """
    检查单个信号的证伪状态

    用于手动触发或信号状态变化时检查
    """
    from apps.signal.application.invalidation_checker import InvalidationCheckService

    if isinstance(signal_id, bool) or not isinstance(signal_id, int) or signal_id <= 0:
        raise BusinessLogicError("signal_id must be a positive integer")

    logger.info("检查信号 %s 的证伪状态...", signal_id)

    try:
        repository = get_signal_repository()
        service = InvalidationCheckService(
            signal_repository=repository,
            forecast_recorder=record_forecast_evaluation_for_signal,
        )
        result = service.check_signal(signal_id)

        if result:
            if result.is_invalidated:
                logger.info(f"信号 {signal_id} 已被证伪: {result.reason}")
            else:
                logger.info(f"信号 {signal_id} 未满足证伪条件: {result.reason}")

            return {
                "signal_id": signal_id,
                "is_invalidated": result.is_invalidated,
                "reason": result.reason,
            }
        else:
            logger.warning(f"信号 {signal_id} 不存在")
            return None

    except (DataFetchError, DatabaseError) as exc:
        logger.warning("检查信号 %s 失败（数据错误）: %s", signal_id, exc)
        record_exception(exc, module="signal", is_handled=True)
        try:
            raise self.retry(exc=exc, countdown=60)
        except MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for signal {signal_id}")
            return {
                "signal_id": signal_id,
                "error": "Signal invalidation data check failed",
                "status": "failed",
            }
    except Exception as exc:
        logger.exception("检查信号 %s 失败（未预期）", signal_id)
        record_exception(exc, module="signal", is_handled=False)
        raise


@typed_shared_task(
    name="signal.cleanup_old_invalidated",
    time_limit=600,
    soft_time_limit=570,
)
def cleanup_old_invalidated_signals(days: int = 90) -> dict[str, object]:
    """
    清理旧的已证伪信号

    默认清理 90 天前的证伪信号，可以归档或删除
    """
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= _MAX_CLEANUP_DAYS:
        raise BusinessLogicError(f"days must be between 1 and {_MAX_CLEANUP_DAYS}")
    logger.info("清理 %s 天前的已证伪信号...", days)

    try:
        repository = get_signal_repository()
        old_ids = repository.get_old_invalidated_signals(days)

        count = len(old_ids)

        # 这里可以选择删除或归档
        # old_signals.delete()

        logger.info(f"找到 {count} 个旧证伪信号: {old_ids}")

        return {"found": count, "signal_ids": old_ids}

    except Exception:
        logger.exception("清理旧证伪信号失败")
        raise


@typed_shared_task(
    name="signal.daily_summary",
    time_limit=600,
    soft_time_limit=570,
)
def send_daily_signal_summary() -> SignalSummary:
    """
    发送每日信号状态摘要

    每天早上发送前一天的状态变化报告
    """
    from datetime import timedelta

    repository = get_signal_repository()

    yesterday = timezone.now() - timedelta(days=1)
    today = timezone.now()

    # 获取新建的信号详情
    new_signal_details = repository.get_signals_created_between(yesterday, today)

    # 获取证伪的信号详情
    invalidated_details = repository.get_signals_invalidated_between(yesterday, today)

    approved_count = repository.count_by_status("approved")

    summary: SignalSummary = {
        "date": yesterday.date().isoformat(),
        "new_signals": len(new_signal_details),
        "invalidated_signals": len(invalidated_details),
        "total_approved": approved_count,
        "notification_sent": False,
    }

    logger.info(f"每日信号摘要: {summary}")

    # 发送通知
    summary["notification_sent"] = _send_signal_summary_notification(
        summary,
        new_signal_details,
        invalidated_details,
    )
    if not summary["notification_sent"]:
        raise DataFetchError("Signal summary notification delivery failed")

    return summary


def _bounded_detail_text(value: object) -> str:
    """Return bounded plain text safe for HTML email rendering."""

    return str(value or "")[:_MAX_DETAIL_TEXT_LENGTH]


def _send_signal_summary_notification(
    summary: SignalSummary,
    new_details: list[dict[str, Any]],
    invalidated_details: list[dict[str, Any]],
) -> bool:
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
        NotificationPriority,
        get_notification_service,
    )

    service = get_notification_service()

    # 构建邮件内容
    subject = f"[AgomTradePro] 每日信号摘要 - {summary['date']}"

    lines = [
        "# 每日信号状态摘要",
        f"**日期**: {summary['date']}",
        "",
        "## 统计数据",
        f"- 新建信号: {summary['new_signals']} 个",
        f"- 证伪信号: {summary['invalidated_signals']} 个",
        f"- 当前有效信号: {summary['total_approved']} 个",
        "",
    ]

    # 添加新建信号详情
    if new_details:
        lines.extend(
            [
                f"## 新建信号 ({len(new_details)})",
                "",
            ]
        )
        for i, signal in enumerate(new_details[:10], 1):
            asset_code = _bounded_detail_text(signal.get("asset_code")) or "N/A"
            logic_desc = _bounded_detail_text(signal.get("logic_desc")) or "N/A"
            lines.append(f"{i}. **{asset_code}** - {logic_desc}")
        if len(new_details) > 10:
            lines.append(f"... 还有 {len(new_details) - 10} 个信号")
        lines.append("")

    # 添加证伪信号详情
    if invalidated_details:
        lines.extend(
            [
                f"## 证伪信号 ({len(invalidated_details)})",
                "",
            ]
        )
        for i, signal in enumerate(invalidated_details[:10], 1):
            details = signal.get("invalidation_details", {})
            raw_reason = details.get("reason") if isinstance(details, Mapping) else None
            reason = _bounded_detail_text(raw_reason) or "N/A"
            asset_code = _bounded_detail_text(signal.get("asset_code")) or "N/A"
            signal_id = _bounded_detail_text(signal.get("id")) or "N/A"
            lines.append(f"{i}. **{asset_code}** (ID: {signal_id}) - {reason}")
        if len(invalidated_details) > 10:
            lines.append(f"... 还有 {len(invalidated_details) - 10} 个信号")
        lines.append("")

    lines.extend(
        [
            "---",
            f"发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
    )

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
            asset_code = html.escape(_bounded_detail_text(signal.get("asset_code")) or "N/A")
            logic_desc = html.escape(_bounded_detail_text(signal.get("logic_desc")) or "N/A")
            html_body += f"<tr><td>{i}</td><td>{asset_code}</td>" f"<td>{logic_desc}</td></tr>"
        html_body += "</table></div>"

    if invalidated_details:
        html_body += """
        <div class="section">
            <h3>证伪信号</h3>
            <table>
                <tr><th>序号</th><th>资产代码</th><th>证伪原因</th></tr>
        """
        for i, signal in enumerate(invalidated_details[:10], 1):
            details = signal.get("invalidation_details", {})
            raw_reason = details.get("reason") if isinstance(details, Mapping) else None
            reason = html.escape(_bounded_detail_text(raw_reason) or "N/A")
            asset_code = html.escape(_bounded_detail_text(signal.get("asset_code")) or "N/A")
            html_body += f"<tr><td>{i}</td><td>{asset_code}</td>" f"<td>{reason}</td></tr>"
        html_body += "</table></div>"

    html_body += f"""
        <div class="footer">
            <p>发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>AgomTradePro - 自动发送，请勿回复</p>
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


def _candidate_emails(value: object) -> Iterable[object]:
    """Yield configured email candidates without iterating string characters."""

    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return value
    return ()


def _get_signal_notification_recipients() -> list[str]:
    """
    获取信号通知收件人列表

    Returns:
        list: 收件人邮箱列表
    """
    user_repo = get_user_repository()
    recipients: set[str] = set()

    # 从配置获取
    config_emails = getattr(settings, "SIGNAL_NOTIFICATION_EMAILS", [])

    # 获取管理员邮箱
    admin_emails = user_repo.get_staff_emails()
    for raw_email in chain(
        _candidate_emails(config_emails),
        _candidate_emails(admin_emails),
    ):
        if not isinstance(raw_email, str):
            continue
        normalized = raw_email.strip().lower()
        if not normalized or len(normalized) > 254:
            continue
        try:
            validate_email(normalized)
        except ValidationError:
            continue
        recipients.add(normalized)
        if len(recipients) >= _MAX_NOTIFICATION_RECIPIENTS:
            break

    return sorted(recipients)
