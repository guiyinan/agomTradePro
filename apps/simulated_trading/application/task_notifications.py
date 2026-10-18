"""Notification helpers used by simulated-trading Celery tasks."""

import logging
from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING, Any, TypedDict

from django.conf import settings
from django.core.mail import send_mail as _django_send_mail

from apps.simulated_trading.application.repository_provider import (
    get_simulated_inspection_repository,
)
from shared.infrastructure.notification_service import NotificationConfig

if TYPE_CHECKING:
    from apps.simulated_trading.application.use_cases import AccountPerformanceResult

logger = logging.getLogger(__name__)


class PerformanceSummary(TypedDict):
    """Serialized account performance with unknown evidence represented as null."""

    account_id: int
    account_name: str
    total_value: float | None
    total_return: float | None
    max_drawdown: float | None
    sharpe_ratio: float | None
    win_rate: float | None
    total_trades: int
    total_positions: int


class PerformanceSummaryEntry(TypedDict):
    """Summary values plus the evidence state needed for email wording."""

    summary: PerformanceSummary
    current_metrics_known: bool
    trade_metrics_known: bool


def build_performance_summary_entry(
    result: "AccountPerformanceResult",
) -> PerformanceSummaryEntry:
    """Serialize one use-case result without turning unknown metrics into zero."""

    account = result["account"]
    current_metrics_known = account.cash_known is True and all(
        position.valuation_known is True for position in result["positions"]
    )
    trade_metrics_known = result["win_rate_known"] is True
    performance_metrics_known = current_metrics_known and trade_metrics_known
    performance_values = result["performance"]
    summary: PerformanceSummary = {
        "account_id": account.account_id,
        "account_name": account.account_name,
        "total_value": account.total_value if current_metrics_known else None,
        "total_return": (performance_values["total_return"] if performance_metrics_known else None),
        "max_drawdown": (performance_values["max_drawdown"] if performance_metrics_known else None),
        "sharpe_ratio": (performance_values["sharpe_ratio"] if performance_metrics_known else None),
        "win_rate": performance_values["win_rate"] if trade_metrics_known else None,
        "total_trades": result["total_trades"],
        "total_positions": result["total_positions"],
    }
    return {
        "summary": summary,
        "current_metrics_known": current_metrics_known,
        "trade_metrics_known": trade_metrics_known,
    }


def build_performance_summary_email(
    entries: Sequence[PerformanceSummaryEntry],
    report_date: date,
) -> tuple[str, str]:
    """Format the evidence-aware performance summary email subject and body."""

    lines = [f"模拟盘绩效日报 ({report_date.isoformat()})"]
    lines.append("=" * 40)
    for entry in entries:
        summary = entry["summary"]
        current_metrics_known = entry["current_metrics_known"]
        trade_metrics_known = entry["trade_metrics_known"]
        financial_unknown_text = "未知（现金或持仓估值不完整）"
        trade_cost_unknown_text = "未知（成交成本信息不完整）"
        performance_unknown_text = (
            financial_unknown_text
            if not current_metrics_known
            else (trade_cost_unknown_text if not trade_metrics_known else "未知（绩效数据不完整）")
        )
        total_value_text = (
            f"{summary['total_value']:,.2f}"
            if summary["total_value"] is not None
            else financial_unknown_text
        )
        total_return = summary["total_return"]
        total_return_text = (
            f"{total_return:.2f}%" if total_return is not None else performance_unknown_text
        )
        max_drawdown = summary["max_drawdown"]
        max_drawdown_text = (
            f"{max_drawdown:.2f}%" if max_drawdown is not None else performance_unknown_text
        )
        sharpe_ratio = summary["sharpe_ratio"]
        sharpe_ratio_text = (
            f"{sharpe_ratio:.2f}" if sharpe_ratio is not None else performance_unknown_text
        )
        win_rate: float | None = summary["win_rate"]
        win_rate_text = (
            f"{win_rate:.2f}%"
            if win_rate is not None
            else (
                "未知"
                if not current_metrics_known
                else trade_cost_unknown_text if not trade_metrics_known else "未知"
            )
        )
        lines.append(
            f"\n账户: {summary['account_name']}"
            f"\n  总资产: {total_value_text}"
            f"\n  总收益: {total_return_text}"
            f"\n  最大回撤: {max_drawdown_text}"
            f"\n  夏普比率: {sharpe_ratio_text}"
            f"\n  胜率: {win_rate_text}"
            f"\n  交易/持仓: {summary['total_trades']}/{summary['total_positions']}"
        )
    subject = f"模拟盘绩效日报 - {report_date.isoformat()}"
    return subject, "\n".join(lines)


def send_mail(*args: Any, **kwargs: Any) -> Any:
    """Send mail through the task-module seam used by task integrations.

    The notification helpers historically exposed ``tasks.send_mail`` as the
    patch point.  Keep that seam while retaining Django's sender as the
    fallback for direct helper use; this avoids coupling tests or operators to
    the helper module's private implementation location.
    """

    try:
        from apps.simulated_trading.application import tasks as task_module

        sender = getattr(task_module, "send_mail", _django_send_mail)
    except (ImportError, AttributeError):
        sender = _django_send_mail
    return sender(*args, **kwargs)


def _require_int_field(payload: dict[str, Any], field_name: str) -> int:
    """Return a required integer identifier from a dynamic task payload."""

    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _send_daily_inspection_email(result: dict[str, Any]) -> None:
    """发送巡检邮件通知（配置来自数据库）。"""
    if not getattr(settings, "DAILY_INSPECTION_EMAIL_ENABLED", True):
        return

    inspection_repo = get_simulated_inspection_repository()
    account_id = _require_int_field(result, "account_id")
    context = inspection_repo.get_account_notification_context(account_id)
    if not context:
        return

    config = context["config"]
    if not config["is_enabled"]:
        return

    status_value = str(result.get("status", "ok")).lower()
    notify_on = {"ok", "warning", "error"} if config["notify_on"] == "all" else {"warning", "error"}
    if status_value not in notify_on:
        return

    recipients: list[str] = []
    if config["include_owner_email"] and context.get("user_email"):
        recipients.append(context["user_email"])

    recipients.extend(
        [str(x).strip() for x in (config["recipient_emails"] or []) if str(x).strip()]
    )

    recipients = sorted(set(recipients))
    if not recipients:
        logger.warning("巡检邮件未发送：无收件人配置 account_id=%s", result.get("account_id"))
        return

    summary = result.get("summary", {})
    checks = result.get("checks", [])
    subject = (
        f"[AgomTradePro] 日更巡检 {status_value.upper()} "
        f"account={result.get('account_id')} date={result.get('inspection_date')}"
    )
    lines = [
        f"account_id: {result.get('account_id')}",
        f"inspection_date: {result.get('inspection_date')}",
        f"status: {result.get('status')}",
        f"macro_regime: {result.get('macro_regime')}",
        f"policy_gear: {result.get('policy_gear')}",
        f"strategy_id: {result.get('strategy_id')}",
        f"position_rule_id: {result.get('position_rule_id')}",
        "",
        "summary:",
        f"- positions_count: {summary.get('positions_count')}",
        f"- rebalance_required_count: {summary.get('rebalance_required_count')}",
        f"- rebalance_assets: {summary.get('rebalance_assets')}",
        f"- total_value: {summary.get('total_value')}",
        f"- current_cash: {summary.get('current_cash')}",
        "",
        "checks(top 10):",
    ]
    for item in checks[:10]:
        lines.append(
            f"- {item.get('asset_code')}: weight={item.get('weight')}, "
            f"target={item.get('target_weight')}, drift={item.get('drift')}, "
            f"action={item.get('rebalance_action')}, qty_suggest={item.get('rebalance_qty_suggest')}"
        )

    send_mail(
        subject=subject,
        message="\n".join(lines),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
        recipient_list=recipients,
        fail_silently=True,
    )
    logger.info("巡检邮件已发送: account_id=%s recipients=%s", result.get("account_id"), recipients)


def _send_rebalance_proposal_notification(result: dict[str, Any]) -> None:
    """发送再平衡建议通知（邮件 + 站内）。"""
    if not result.get("proposal_id"):
        return

    account_id = _require_int_field(result, "account_id")
    proposal_id = _require_int_field(result, "proposal_id")
    summary = result.get("summary", {})

    inspection_repo = get_simulated_inspection_repository()
    context = inspection_repo.get_account_notification_context(account_id)
    if not context:
        logger.warning("无法发送再平衡建议通知：账户不存在 account_id=%s", account_id)
        return

    proposal = inspection_repo.get_rebalance_proposal_detail(proposal_id)
    if not proposal:
        logger.warning("无法发送再平衡建议通知：建议不存在 proposal_id=%s", proposal_id)
        return

    config = context["config"]
    if not config["is_enabled"]:
        return

    # 收集收件人邮箱
    recipients: list[str] = []
    if config["include_owner_email"] and context.get("user_email"):
        recipients.append(context["user_email"])

    recipients.extend(
        [str(x).strip() for x in (config["recipient_emails"] or []) if str(x).strip()]
    )
    recipients = sorted(set(recipients))

    # 发送邮件通知
    if recipients:
        subject = (
            f"[AgomTradePro] 再平衡建议待审核 "
            f"account={context['account_name']} proposal_id={proposal_id}"
        )
        lines = [
            f"账户: {context['account_name']} (ID: {account_id})",
            f"建议ID: {proposal_id}",
            f"巡检日期: {result.get('inspection_date')}",
            f"优先级: {proposal['priority_display']}",
            f"状态: {proposal['status_display']}",
            "",
            "再平衡摘要:",
            f"- 需要调整的资产数: {summary.get('rebalance_required_count', 0)}",
            f"- 买入操作: {len([p for p in proposal['proposals'] if p['action'] == 'buy'])}",
            f"- 卖出操作: {len([p for p in proposal['proposals'] if p['action'] == 'sell'])}",
            f"- 预计交易金额: {sum(p.get('estimated_amount', 0) for p in proposal['proposals']):.2f} 元",
            "",
            "调整明细:",
        ]

        for item in proposal["proposals"][:10]:
            action_emoji = "🔴" if item["action"] == "sell" else "🟢"
            lines.append(
                f"{action_emoji} {item['asset_code']} ({item['asset_name']}): "
                f"{item['action']} {item['suggested_quantity']} 股, "
                f"金额约 {item['estimated_amount']:.2f} 元"
            )

        if len(proposal["proposals"]) > 10:
            lines.append(f"... 还有 {len(proposal['proposals']) - 10} 个资产")

        lines.extend(
            [
                "",
                f"原因: {proposal['source_description']}",
                "",
                "请登录系统审核并执行此再平衡建议。",
                "-" * 50,
            ]
        )

        send_mail(
            subject=subject,
            message="\n".join(lines),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
            recipient_list=recipients,
            fail_silently=True,
        )
        logger.info("再平衡建议邮件已发送: proposal_id=%s recipients=%s", proposal_id, recipients)

    # 创建站内通知（如果用户存在）
    user_id = context.get("user_id")
    if isinstance(user_id, int) and not isinstance(user_id, bool):
        from shared.infrastructure.notification_service import (
            InAppNotificationChannel,
            NotificationMessage,
            NotificationPriority,
            NotificationRecipient,
        )

        try:
            channel = InAppNotificationChannel()
            message = NotificationMessage(
                subject="再平衡建议待审核",
                body=f"账户 {context['account_name']} 的日更巡检发现了 {summary.get('rebalance_required_count', 0)} 个需要调整的资产，请审核再平衡建议 #{proposal_id}。",
                priority=NotificationPriority.HIGH,
                metadata={
                    "proposal_id": proposal_id,
                    "account_id": account_id,
                    "inspection_date": result.get("inspection_date"),
                },
                tags=["rebalance", "daily_inspection"],
            )

            recipient = NotificationRecipient(user_id=user_id)
            result_notify = channel.send(message, recipient, NotificationConfig())

            if result_notify.success:
                logger.info("站内通知已发送: user_id=%s proposal_id=%s", user_id, proposal_id)
            else:
                logger.warning("站内通知发送失败: %s", result_notify.error_message)

        except Exception as e:
            logger.warning("创建站内通知失败: %s", e)

    # 记录通知历史
    _record_notification_history(
        account_id=account_id,
        account_name=context["account_name"],
        account_user_id=(
            user_id if isinstance(user_id, int) and not isinstance(user_id, bool) else None
        ),
        proposal=proposal,
        notification_type="rebalance_proposal",
        recipients=recipients,
        status="sent" if recipients else "skipped",
    )


def _record_notification_history(
    account_id: int,
    account_name: str,
    account_user_id: int | None,
    proposal: Any,
    notification_type: str,
    recipients: list[str],
    status: str,
) -> None:
    """记录通知历史"""
    try:
        inspection_repo = get_simulated_inspection_repository()
        inspection_repo.record_notification_history(
            account_id=account_id,
            proposal_id=proposal.get("proposal_id"),
            notification_type=notification_type,
            recipients=recipients,
            status=status,
            subject=f"再平衡建议待审核 #{proposal.get('proposal_id')}",
            body=f"账户 {account_name} 的再平衡建议需要审核。",
            recipient_user_id=account_user_id,
        )

        logger.debug("通知历史已记录: account_id=%s type=%s", account_id, notification_type)

    except Exception as e:
        logger.warning("记录通知历史失败: %s", e)
