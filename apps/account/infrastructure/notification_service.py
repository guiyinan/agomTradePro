"""
Notification Service - Account Module

通知服务实现，用于止损/止盈触发时发送通知。
遵循四层架构：Infrastructure 层实现 Domain 层定义的协议。
"""

import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string

from apps.account.domain.interfaces import (
    StopLossNotificationData,
    StopLossNotificationPort,
)
from apps.events.domain.entities import DomainEvent, EventType, create_event
from core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class EmailStopLossNotificationService(StopLossNotificationPort):
    """
    邮件通知服务

    当止损/止盈触发时，发送邮件通知用户。
    同时记录事件到 events 模块以供审计。
    """

    def __init__(self):
        from apps.events.infrastructure.event_store import DatabaseEventStore
        self.event_store = DatabaseEventStore()

    def notify_stop_loss_triggered(self, data: StopLossNotificationData) -> bool:
        """
        发送止损触发通知

        Args:
            data: 止损通知数据

        Returns:
            是否发送成功
        """
        try:
            # 记录事件
            self._log_stop_loss_event(data)

            # 发送邮件通知
            if self._should_send_email(data.user_id):
                return self._send_stop_loss_email(data)

            logger.info(
                f"止损触发通知已记录（未发送邮件）: 用户 {data.user_id}, "
                f"持仓 {data.position_id}, {data.asset_code}"
            )
            return True

        except Exception as e:
            logger.error(f"发送止损通知失败: {e}", exc_info=True)
            # 通知失败不应影响止损执行
            return False

    def notify_take_profit_triggered(self, data: StopLossNotificationData) -> bool:
        """
        发送止盈触发通知

        Args:
            data: 止盈通知数据

        Returns:
            是否发送成功
        """
        try:
            # 记录事件
            self._log_take_profit_event(data)

            # 发送邮件通知
            if self._should_send_email(data.user_id):
                return self._send_take_profit_email(data)

            logger.info(
                f"止盈触发通知已记录（未发送邮件）: 用户 {data.user_id}, "
                f"持仓 {data.position_id}, {data.asset_code}"
            )
            return True

        except Exception as e:
            logger.error(f"发送止盈通知失败: {e}", exc_info=True)
            return False

    def _should_send_email(self, user_id: int) -> bool:
        """
        检查是否应该发送邮件

        Args:
            user_id: 用户ID

        Returns:
            是否应该发送邮件
        """
        # 检查用户是否启用了邮件通知
        try:
            user = User._default_manager.get(id=user_id)
            if not user.email:
                return False

            # 可以在这里添加用户偏好设置检查
            # 例如: user_profile.email_notifications_enabled

            return getattr(settings, 'SEND_EMAIL_NOTIFICATIONS', False)

        except User.DoesNotExist:
            logger.warning(f"用户 {user_id} 不存在，跳过邮件通知")
            return False

    def _send_stop_loss_email(self, data: StopLossNotificationData) -> bool:
        """
        发送止损邮件通知

        Args:
            data: 通知数据

        Returns:
            是否发送成功
        """
        subject = f"止损触发通知 - {data.asset_code}"

        # 构建邮件内容
        context = {
            'user_email': data.user_email,
            'asset_code': data.asset_code,
            'trigger_type': data.trigger_type,
            'trigger_price': data.trigger_price,
            'trigger_time': data.trigger_time,
            'trigger_reason': data.trigger_reason,
            'pnl': data.pnl,
            'pnl_pct': data.pnl_pct,
            'shares_closed': data.shares_closed,
        }

        # 纯文本版本
        message = self._build_stop_loss_text_message(context)

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomtradepro.com'),
                recipient_list=[data.user_email],
                fail_silently=False,
            )
            logger.info(f"止损邮件已发送给 {data.user_email}")
            return True

        except Exception as e:
            logger.error(f"发送止损邮件失败: {e}", exc_info=True)
            raise ExternalServiceError(
                message=f"邮件发送失败: {e}",
                code="EMAIL_SEND_FAILED"
            )

    def _send_take_profit_email(self, data: StopLossNotificationData) -> bool:
        """
        发送止盈邮件通知

        Args:
            data: 通知数据

        Returns:
            是否发送成功
        """
        subject = f"止盈触发通知 - {data.asset_code}"

        # 构建邮件内容
        context = {
            'user_email': data.user_email,
            'asset_code': data.asset_code,
            'trigger_price': data.trigger_price,
            'trigger_time': data.trigger_time,
            'trigger_reason': data.trigger_reason,
            'pnl': data.pnl,
            'pnl_pct': data.pnl_pct,
            'shares_closed': data.shares_closed,
        }

        # 纯文本版本
        message = self._build_take_profit_text_message(context)

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@agomtradepro.com'),
                recipient_list=[data.user_email],
                fail_silently=False,
            )
            logger.info(f"止盈邮件已发送给 {data.user_email}")
            return True

        except Exception as e:
            logger.error(f"发送止盈邮件失败: {e}", exc_info=True)
            raise ExternalServiceError(
                message=f"邮件发送失败: {e}",
                code="EMAIL_SEND_FAILED"
            )

    def _build_stop_loss_text_message(self, context: dict) -> str:
        """构建止损通知纯文本内容"""
        pnl_sign = "+" if float(context['pnl']) >= 0 else ""
        return f"""
您的持仓已触发止损。

资产代码: {context['asset_code']}
止损类型: {context['trigger_type']}
触发价格: {context['trigger_price']}
触发时间: {context['trigger_time']}
触发原因: {context['trigger_reason']}

盈亏: {pnl_sign}{context['pnl']} ({pnl_sign}{context['pnl_pct']:.2f}%)
{'平仓数量: ' + str(context['shares_closed']) if context['shares_closed'] else '全部平仓'}

请注意及时查看您的账户状态。

---
AgomTradePro 智能投顾系统
此邮件由系统自动发送，请勿回复。
""".strip()

    def _build_take_profit_text_message(self, context: dict) -> str:
        """构建止盈通知纯文本内容"""
        pnl_sign = "+" if float(context['pnl']) >= 0 else ""
        return f"""
您的持仓已触发止盈。

资产代码: {context['asset_code']}
触发价格: {context['trigger_price']}
触发时间: {context['trigger_time']}
触发原因: {context['trigger_reason']}

盈亏: {pnl_sign}{context['pnl']} ({pnl_sign}{context['pnl_pct']:.2f}%)
{'平仓数量: ' + str(context['shares_closed']) if context['shares_closed'] else '全部平仓'}

恭喜您获得收益！

---
AgomTradePro 智能投顾系统
此邮件由系统自动发送，请勿回复。
""".strip()

    def _log_stop_loss_event(self, data: StopLossNotificationData) -> None:
        """
        记录止损事件到 events 模块

        Args:
            data: 通知数据
        """
        try:
            event = create_event(
                event_type=EventType.STOP_LOSS_TRIGGERED,
                payload={
                    "user_id": data.user_id,
                    "asset_code": data.asset_code,
                    "trigger_type": data.trigger_type,
                    "trigger_price": str(data.trigger_price),
                    "trigger_reason": data.trigger_reason,
                    "pnl": str(data.pnl),
                    "pnl_pct": data.pnl_pct,
                    "shares_closed": data.shares_closed,
                },
                metadata={"position_id": str(data.position_id), "aggregate_type": "position"},
            )
            self.event_store.append(event)
            logger.debug(f"止损事件已记录: position_id={data.position_id}")

        except Exception as e:
            # 事件记录失败不应影响止损执行
            logger.warning(f"记录止损事件失败: {e}")

    def _log_take_profit_event(self, data: StopLossNotificationData) -> None:
        """
        记录止盈事件到 events 模块

        Args:
            data: 通知数据
        """
        try:
            event = create_event(
                event_type=EventType.TAKE_PROFIT_TRIGGERED,
                payload={
                    "user_id": data.user_id,
                    "asset_code": data.asset_code,
                    "trigger_price": str(data.trigger_price),
                    "trigger_reason": data.trigger_reason,
                    "pnl": str(data.pnl),
                    "pnl_pct": data.pnl_pct,
                    "shares_closed": data.shares_closed,
                },
                metadata={"position_id": str(data.position_id), "aggregate_type": "position"},
            )
            self.event_store.append(event)
            logger.debug(f"止盈事件已记录: position_id={data.position_id}")

        except Exception as e:
            # 事件记录失败不应影响止盈执行
            logger.warning(f"记录止盈事件失败: {e}")


class InMemoryStopLossNotificationService(StopLossNotificationPort):
    """
    内存通知服务（用于测试和开发环境）

    将通知记录到日志，不发送实际邮件。
    """

    def notify_stop_loss_triggered(self, data: StopLossNotificationData) -> bool:
        """记录止损触发日志"""
        logger.info(
            f"[止损触发] 用户: {data.user_id}, 持仓: {data.position_id}, "
            f"资产: {data.asset_code}, 类型: {data.trigger_type}, "
            f"盈亏: {data.pnl} ({data.pnl_pct:.2f}%), "
            f"原因: {data.trigger_reason}"
        )
        return True

    def notify_take_profit_triggered(self, data: StopLossNotificationData) -> bool:
        """记录止盈触发日志"""
        logger.info(
            f"[止盈触发] 用户: {data.user_id}, 持仓: {data.position_id}, "
            f"资产: {data.asset_code}, "
            f"盈亏: {data.pnl} ({data.pnl_pct:.2f}%), "
            f"原因: {data.trigger_reason}"
        )
        return True
