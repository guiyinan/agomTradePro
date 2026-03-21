"""
Infrastructure Layer - Notification Service Implementations

实现通知服务的具体实现，包括：
- 邮件通知（Django send_mail）
- 站内通知（数据库）
- 审计日志装饰器
- 服务工厂
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from django.core.mail import send_mail
from django.conf import settings

from ..domain.interfaces import (
    NotificationServicePort,
    PolicyAlertServicePort,
    NotificationMessage,
    NotificationChannel,
)
from ..domain.entities import PolicyLevel, PolicyEvent


logger = logging.getLogger(__name__)


# ========================================
# 基础通知服务实现
# ========================================


class LoggingNotificationService:
    """日志通知服务

    将所有通知记录到日志，用于开发和调试。
    同时作为其他服务的基类，提供日志记录能力。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def send(self, message: NotificationMessage) -> bool:
        """记录通知到日志"""
        if not self.enabled:
            return True

        log_level = self._get_log_level(message.priority)
        log_func = getattr(logger, log_level)

        log_func(
            f"[Notification] {message.channel}:{message.priority} - {message.title}\n"
            f"Recipients: {message.recipients}\n"
            f"Content: {message.content[:200]}..."
        )

        return True

    def send_batch(self, messages: List[NotificationMessage]) -> dict:
        """批量记录通知"""
        success_count = 0
        errors = []

        for msg in messages:
            if self.send(msg):
                success_count += 1
            else:
                errors.append(f"Failed to send: {msg.title}")

        return {"success": success_count, "failed": len(errors), "errors": errors}

    def _get_log_level(self, priority: str) -> str:
        """根据优先级获取日志级别"""
        priority_map = {
            "critical": "error",
            "high": "warning",
            "normal": "info",
            "low": "debug",
        }
        return priority_map.get(priority.lower(), "info")


class EmailNotificationService(LoggingNotificationService):
    """邮件通知服务

    使用 Django 的 send_mail 发送邮件通知。
    支持从配置读取默认收件人。
    """

    def __init__(
        self,
        enabled: bool = True,
        default_recipients: Optional[List[str]] = None,
    ):
        super().__init__(enabled)
        self.default_recipients = default_recipients or getattr(
            settings, "POLICY_ALERT_EMAILS", []
        )

    def send(self, message: NotificationMessage) -> bool:
        """发送邮件通知"""
        if not self.enabled:
            logger.debug(f"Email notification disabled, skipping: {message.title}")
            return True

        # 确定收件人
        recipients = message.recipients or self.default_recipients
        if not recipients:
            logger.warning(f"No recipients for email: {message.title}")
            return False

        # 检查邮件配置
        if not getattr(settings, "EMAIL_BACKEND", None):
            logger.warning("EMAIL_BACKEND not configured, falling back to logging")
            return super().send(message)

        try:
            # 构建邮件主题
            prefix = self._get_priority_prefix(message.priority)
            subject = f"{prefix} {message.title}"

            # 发送邮件
            send_mail(
                subject=subject,
                message=message.content,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
                recipient_list=recipients,
                fail_silently=False,
            )

            logger.info(f"Email sent successfully to {len(recipients)} recipients: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}", exc_info=True)
            # 降级到日志记录
            return super().send(message)

    def send_batch(self, messages: List[NotificationMessage]) -> dict:
        """批量发送邮件（合并发送）"""
        if not messages:
            return {"success": 0, "failed": 0, "errors": []}

        # 合并所有邮件内容
        all_content = []
        for msg in messages:
            prefix = self._get_priority_prefix(msg.priority)
            all_content.append(f"{prefix} {msg.title}\n{msg.content}\n")
            all_content.append("-" * 50 + "\n")

        # 合并收件人
        all_recipients = set()
        for msg in messages:
            all_recipients.update(msg.recipients or self.default_recipients)
        all_recipients = list(all_recipients)

        # 发送合并邮件
        merged_message = NotificationMessage(
            title=f"Policy Notifications ({len(messages)} items)",
            content="\n".join(all_content),
            channel=NotificationChannel.EMAIL,
            priority="high",
            recipients=all_recipients,
        )

        success = self.send(merged_message)
        return {
            "success": len(messages) if success else 0,
            "failed": 0 if success else len(messages),
            "errors": [],
        }

    def _get_priority_prefix(self, priority: str) -> str:
        """获取优先级前缀"""
        prefix_map = {
            "critical": "[CRITICAL]",
            "high": "[HIGH]",
            "normal": "[INFO]",
            "low": "[LOW]",
        }
        return prefix_map.get(priority.lower(), "[NOTICE]")


class InAppNotificationService:
    """站内通知服务

    将通知存储到数据库，供用户在界面查看。
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def send(self, message: NotificationMessage) -> bool:
        """创建站内通知记录"""
        if not self.enabled:
            return True

        try:
            # 导入模型（延迟导入避免循环依赖）
            from .models import InAppNotification

            # 为每个收件人创建通知
            if not message.recipients:
                # 如果没有指定收件人，创建全局通知
                InAppNotification.objects.create(
                    title=message.title,
                    content=message.content,
                    channel=message.channel,
                    priority=message.priority,
                    metadata=message.metadata,
                    is_global=True,
                )
            else:
                # 为每个用户创建通知
                for recipient in message.recipients:
                    InAppNotification.objects.create(
                        title=message.title,
                        content=message.content,
                        channel=message.channel,
                        priority=message.priority,
                        recipient_username=recipient,
                        metadata=message.metadata,
                        is_global=False,
                    )

            logger.debug(f"In-app notification created: {message.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to create in-app notification: {e}", exc_info=True)
            return False

    def send_batch(self, messages: List[NotificationMessage]) -> dict:
        """批量创建站内通知"""
        success_count = 0
        errors = []

        for msg in messages:
            if self.send(msg):
                success_count += 1
            else:
                errors.append(f"Failed to create: {msg.title}")

        return {"success": success_count, "failed": len(errors), "errors": errors}


# ========================================
# 政策告警服务实现
# ========================================


class PolicyAlertService(PolicyAlertServicePort):
    """政策告警服务

    实现政策相关的告警逻辑。
    可以组合多种通知渠道。
    """

    def __init__(
        self,
        email_service: Optional[EmailNotificationService] = None,
        in_app_service: Optional[InAppNotificationService] = None,
    ):
        self.email_service = email_service
        self.in_app_service = in_app_service

    def send_policy_alert(
        self,
        level: PolicyLevel,
        event: PolicyEvent,
        status: Any
    ) -> bool:
        """发送政策档位告警

        构建告警消息并通过配置的渠道发送。
        """
        try:
            # 确定告警级别
            alert_level = "critical" if level == PolicyLevel.P3 else "warning"

            # 构建消息内容
            title = f"政策状态告警: {level.value} - {getattr(status, 'level_name', level.value)}"
            content = self._build_alert_content(level, event, status, alert_level)

            # 创建邮件通知
            email_sent = True
            if self.email_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.EMAIL,
                    priority=alert_level,
                    metadata={
                        "level": level.value,
                        "event_date": event.event_date.isoformat(),
                        "event_title": event.title,
                    }
                )
                email_sent = self.email_service.send(message)

            # 创建站内通知
            in_app_sent = True
            if self.in_app_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.IN_APP,
                    priority=alert_level,
                    metadata={
                        "level": level.value,
                        "event_date": event.event_date.isoformat(),
                        "evidence_url": event.evidence_url,
                    }
                )
                in_app_sent = self.in_app_service.send(message)

            success = email_sent and in_app_sent
            if success:
                logger.info(f"Policy alert sent successfully: {level.value}")

            return success

        except Exception as e:
            logger.error(f"Failed to send policy alert: {e}", exc_info=True)
            return False

    def send_transition_summary(self, changes: List[dict]) -> bool:
        """发送档位变更摘要"""
        if not changes:
            return True

        try:
            title = f"政策档位变更摘要 ({len(changes)} 项)"
            content = self._build_transition_content(changes)

            # 发送邮件
            email_sent = True
            if self.email_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.EMAIL,
                    priority="normal",
                    metadata={"changes_count": len(changes)},
                )
                email_sent = self.email_service.send(message)

            # 创建站内通知
            in_app_sent = True
            if self.in_app_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.IN_APP,
                    priority="normal",
                )
                in_app_sent = self.in_app_service.send(message)

            return email_sent and in_app_sent

        except Exception as e:
            logger.error(f"Failed to send transition summary: {e}", exc_info=True)
            return False

    def send_sla_alert(self, p23_count: int, normal_count: int) -> bool:
        """发送SLA超时告警"""
        if p23_count == 0 and normal_count == 0:
            return True

        try:
            title = "SLA 超时告警"
            content = f"""SLA 超时警告

P2/P3 超时: {p23_count} 项
普通超时: {normal_count} 项

请及时处理待审核事件！
"""

            # 发送邮件
            email_sent = True
            if self.email_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.EMAIL,
                    priority="high",
                    metadata={"p23_count": p23_count, "normal_count": normal_count},
                )
                email_sent = self.email_service.send(message)

            # 创建站内通知
            in_app_sent = True
            if self.in_app_service:
                message = NotificationMessage(
                    title=title,
                    content=content,
                    channel=NotificationChannel.IN_APP,
                    priority="high",
                )
                in_app_sent = self.in_app_service.send(message)

            return email_sent and in_app_sent

        except Exception as e:
            logger.error(f"Failed to send SLA alert: {e}", exc_info=True)
            return False

    def _build_alert_content(
        self,
        level: PolicyLevel,
        event: PolicyEvent,
        status: Any,
        alert_level: str
    ) -> str:
        """构建告警消息内容"""
        content = f"""**政策状态告警**

档位: {level.value} - {getattr(status, 'level_name', level.value)}
标题: {event.title}
描述: {event.description}
日期: {event.event_date}

**响应措施**:
- 现金调整: +{getattr(status.response_config, 'cash_adjustment', 0)}%
- 行动: {getattr(status.response_config, 'market_action', 'N/A').value if hasattr(getattr(status, 'response_config', None), 'market_action') else 'N/A'}
"""

        if hasattr(status, 'response_config') and hasattr(status.response_config, 'signal_pause_hours'):
            if status.response_config.signal_pause_hours:
                content += f"- 信号暂停: {status.response_config.signal_pause_hours} 小时\n"

        content += f"""
**建议**:
{chr(10).join(f'- {r}' for r in getattr(status, 'recommendations', []))}

证据: {event.evidence_url}
"""
        return content

    def _build_transition_content(self, changes: List[dict]) -> str:
        """构建变更摘要内容"""
        content = "**政策档位变更摘要**\n\n"

        for change in changes:
            content += f"""
- {change['date']}: {change['from']} -> {change['to']}
  标题: {change['title']}
"""

        return content


# ========================================
# 服务工厂
# ========================================


class NotificationServiceFactory:
    """通知服务工厂

    根据配置创建通知服务实例。
    """

    _email_service: Optional[EmailNotificationService] = None
    _in_app_service: Optional[InAppNotificationService] = None
    _alert_service: Optional[PolicyAlertService] = None

    @classmethod
    def get_email_service(cls) -> EmailNotificationService:
        """获取邮件通知服务（单例）"""
        if cls._email_service is None:
            from django.conf import settings
            default_recipients = getattr(settings, "POLICY_ALERT_EMAILS", [])
            enabled = getattr(settings, "POLICY_EMAIL_NOTIFICATIONS_ENABLED", True)
            cls._email_service = EmailNotificationService(
                enabled=enabled,
                default_recipients=default_recipients
            )
        return cls._email_service

    @classmethod
    def get_in_app_service(cls) -> InAppNotificationService:
        """获取站内通知服务（单例）"""
        if cls._in_app_service is None:
            from django.conf import settings
            enabled = getattr(settings, "POLICY_IN_APP_NOTIFICATIONS_ENABLED", True)
            cls._in_app_service = InAppNotificationService(enabled=enabled)
        return cls._in_app_service

    @classmethod
    def get_alert_service(cls) -> PolicyAlertService:
        """获取政策告警服务（单例）"""
        if cls._alert_service is None:
            cls._alert_service = PolicyAlertService(
                email_service=cls.get_email_service(),
                in_app_service=cls.get_in_app_service(),
            )
        return cls._alert_service

    @classmethod
    def reset(cls):
        """重置单例（主要用于测试）"""
        cls._email_service = None
        cls._in_app_service = None
        cls._alert_service = None
