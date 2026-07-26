"""
Infrastructure Layer - Notification Service Implementations

实现通知服务的具体实现，包括：
- 邮件通知（Django send_mail）
- 站内通知（数据库）
- 审计日志装饰器
- 服务工厂
"""

import logging
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Manager

from ..domain.entities import PolicyEvent, PolicyLevel
from ..domain.interfaces import (
    NotificationBatchResult,
    NotificationChannel,
    NotificationMessage,
    PolicyAlertServicePort,
    PolicyTransitionChange,
)
from .models import InAppNotification

logger = logging.getLogger(__name__)


# ========================================
# 基础通知服务实现
# ========================================


class LoggingNotificationService:
    """日志通知服务

    将所有通知记录到日志，用于开发和调试。
    同时作为其他服务的基类，提供日志记录能力。
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def send(self, message: NotificationMessage) -> bool:
        """记录通知到日志"""
        if not self.enabled:
            return False

        log_level = self._get_log_level(message.priority)
        log_func = getattr(logger, log_level)

        log_func(
            "[Notification] channel=%s priority=%s recipient_count=%d",
            message.channel,
            message.priority,
            len(message.recipients),
        )

        return True

    def send_batch(self, messages: list[NotificationMessage]) -> NotificationBatchResult:
        """批量记录通知"""
        success_count = 0
        errors: list[str] = []

        for index, msg in enumerate(messages):
            if self.send(msg):
                success_count += 1
            else:
                errors.append(f"message_{index}_not_logged")

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
        default_recipients: list[str] | None = None,
    ) -> None:
        super().__init__(enabled)
        configured_recipients = (
            default_recipients
            if default_recipients is not None
            else getattr(settings, "POLICY_ALERT_EMAILS", [])
        )
        self.default_recipients = self._normalize_recipients(configured_recipients)

    def send(self, message: NotificationMessage) -> bool:
        """发送邮件通知"""
        if not self.enabled:
            logger.debug("Email notification disabled")
            return False

        # 确定收件人
        recipients = self._normalize_recipients(message.recipients or self.default_recipients)
        if not recipients:
            logger.warning("Email notification has no valid recipients")
            return False

        # 检查邮件配置
        if not getattr(settings, "EMAIL_BACKEND", None):
            logger.warning("EMAIL_BACKEND is not configured")
            return False

        try:
            # 构建邮件主题
            prefix = self._get_priority_prefix(message.priority)
            subject = f"{prefix} {message.title}"

            # 发送邮件
            delivered_count = send_mail(
                subject=subject,
                message=message.content,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com"),
                recipient_list=recipients,
                fail_silently=False,
            )

            if delivered_count != 1:
                logger.error(
                    "Email backend did not confirm delivery",
                    extra={"recipient_count": len(recipients)},
                )
                return False
            logger.info(
                "Policy email delivered",
                extra={"recipient_count": len(recipients)},
            )
            return True

        except Exception:
            logger.error("Failed to send policy email", exc_info=True)
            return False

    def send_batch(self, messages: list[NotificationMessage]) -> NotificationBatchResult:
        """Send messages separately to preserve recipient isolation."""

        success_count = 0
        errors: list[str] = []
        for index, message in enumerate(messages):
            if self.send(message):
                success_count += 1
            else:
                errors.append(f"message_{index}_delivery_failed")
        return {
            "success": success_count,
            "failed": len(errors),
            "errors": errors,
        }

    @staticmethod
    def _normalize_recipients(values: object) -> list[str]:
        if not isinstance(values, (list, tuple, set, frozenset)):
            return []
        return list(
            dict.fromkeys(
                value.strip() for value in values if isinstance(value, str) and value.strip()
            )
        )

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

    def __init__(
        self,
        enabled: bool = True,
        manager: Manager[InAppNotification] | None = None,
    ) -> None:
        self.enabled = enabled
        self.manager = manager or InAppNotification._default_manager

    def send(self, message: NotificationMessage) -> bool:
        """创建站内通知记录"""
        if not self.enabled:
            return False

        try:
            records = self._build_records(message)
            with transaction.atomic():
                self.manager.bulk_create(records)
            logger.debug(
                "In-app policy notification persisted",
                extra={"record_count": len(records)},
            )
            return True

        except Exception:
            logger.error("Failed to persist in-app policy notification", exc_info=True)
            return False

    def send_batch(self, messages: list[NotificationMessage]) -> NotificationBatchResult:
        """Persist an entire message batch atomically."""

        if not messages:
            return {"success": 0, "failed": 0, "errors": []}
        if not self.enabled:
            return {
                "success": 0,
                "failed": len(messages),
                "errors": ["in_app_notifications_disabled"],
            }
        try:
            records = [record for message in messages for record in self._build_records(message)]
            with transaction.atomic():
                self.manager.bulk_create(records)
            return {"success": len(messages), "failed": 0, "errors": []}
        except Exception:
            logger.error("Failed to persist in-app notification batch", exc_info=True)
            return {
                "success": 0,
                "failed": len(messages),
                "errors": ["in_app_batch_persistence_failed"],
            }

    @staticmethod
    def _build_records(message: NotificationMessage) -> list[InAppNotification]:
        recipients = list(
            dict.fromkeys(
                recipient.strip()
                for recipient in message.recipients
                if isinstance(recipient, str) and recipient.strip()
            )
        )
        if message.recipients and not recipients:
            raise ValueError("direct notification has no valid recipients")
        if not recipients:
            return [
                InAppNotification(
                    title=message.title,
                    content=message.content,
                    channel=message.channel,
                    priority=message.priority,
                    metadata=message.metadata,
                    is_global=True,
                )
            ]
        return [
            InAppNotification(
                title=message.title,
                content=message.content,
                channel=message.channel,
                priority=message.priority,
                recipient_username=recipient,
                metadata=message.metadata,
                is_global=False,
            )
            for recipient in recipients
        ]


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
        email_service: EmailNotificationService | None = None,
        in_app_service: InAppNotificationService | None = None,
    ):
        self.email_service = email_service
        self.in_app_service = in_app_service

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Send a generic policy alert through every configured channel."""

        if self.email_service is None and self.in_app_service is None:
            return False
        alert_metadata = metadata or {}
        priority = self._normalize_priority(level)
        email_sent = True
        if self.email_service:
            email_sent = self.email_service.send(
                NotificationMessage(
                    title=title,
                    content=message,
                    channel=NotificationChannel.EMAIL,
                    priority=priority,
                    metadata=alert_metadata,
                )
            )

        in_app_sent = True
        if self.in_app_service:
            in_app_sent = self.in_app_service.send(
                NotificationMessage(
                    title=title,
                    content=message,
                    channel=NotificationChannel.IN_APP,
                    priority=priority,
                    metadata=alert_metadata,
                )
            )

        return email_sent and in_app_sent

    def send_policy_alert(self, level: PolicyLevel, event: PolicyEvent, status: object) -> bool:
        """发送政策档位告警

        构建告警消息并通过配置的渠道发送。
        """
        try:
            if self.email_service is None and self.in_app_service is None:
                return False
            # 确定告警级别
            alert_level = "critical" if level == PolicyLevel.P3 else "high"

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
                    },
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
                    },
                )
                in_app_sent = self.in_app_service.send(message)

            success = email_sent and in_app_sent
            if success:
                logger.info(f"Policy alert sent successfully: {level.value}")

            return success

        except Exception:
            logger.error("Failed to send policy alert", exc_info=True)
            return False

    def send_transition_summary(self, changes: list[dict[str, str]]) -> bool:
        """发送档位变更摘要"""
        if not changes:
            return True

        try:
            if self.email_service is None and self.in_app_service is None:
                return False
            normalized_changes = self._normalize_transition_changes(changes)
            title = f"政策档位变更摘要 ({len(changes)} 项)"
            content = self._build_transition_content(normalized_changes)

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

        except (TypeError, ValueError):
            logger.warning("Invalid policy transition summary payload", exc_info=True)
            return False
        except Exception:
            logger.error("Failed to send transition summary", exc_info=True)
            return False

    def send_sla_alert(self, p23_count: int, normal_count: int) -> bool:
        """发送SLA超时告警"""
        if (
            isinstance(p23_count, bool)
            or isinstance(normal_count, bool)
            or p23_count < 0
            or normal_count < 0
        ):
            return False
        if p23_count == 0 and normal_count == 0:
            return True

        try:
            if self.email_service is None and self.in_app_service is None:
                return False
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

        except Exception:
            logger.error("Failed to send SLA alert", exc_info=True)
            return False

    def _build_alert_content(
        self, level: PolicyLevel, event: PolicyEvent, status: object, alert_level: str
    ) -> str:
        """构建告警消息内容"""
        del alert_level
        level_name = self._string_attribute(status, "level_name", level.value)
        response_config = getattr(status, "response_config", None)
        cash_adjustment = self._string_attribute(response_config, "cash_adjustment", "0")
        market_action = getattr(response_config, "market_action", None)
        market_action_value = self._string_attribute(market_action, "value", "N/A")
        signal_pause_hours = getattr(response_config, "signal_pause_hours", None)
        raw_recommendations = getattr(status, "recommendations", [])
        recommendations = (
            [item for item in raw_recommendations if isinstance(item, str)]
            if isinstance(raw_recommendations, list)
            else []
        )
        content = f"""**政策状态告警**

档位: {level.value} - {level_name}
标题: {event.title}
描述: {event.description}
日期: {event.event_date}

**响应措施**:
- 现金调整: +{cash_adjustment}%
- 行动: {market_action_value}
"""

        if signal_pause_hours:
            content += f"- 信号暂停: {signal_pause_hours} 小时\n"

        content += f"""
**建议**:
{chr(10).join(f'- {recommendation}' for recommendation in recommendations)}

证据: {event.evidence_url}
"""
        return content

    def _build_transition_content(self, changes: list[PolicyTransitionChange]) -> str:
        """构建变更摘要内容"""
        content = "**政策档位变更摘要**\n\n"

        for change in changes:
            content += f"""
- {change['date']}: {change['from']} -> {change['to']}
  标题: {change['title']}
"""

        return content

    @staticmethod
    def _normalize_transition_changes(
        changes: list[dict[str, str]],
    ) -> list[PolicyTransitionChange]:
        normalized: list[PolicyTransitionChange] = []
        required_fields = ("date", "from", "to", "title")
        for change in changes:
            if not isinstance(change, Mapping):
                raise TypeError("transition change must be an object")
            values: dict[str, str] = {}
            for field in required_fields:
                value = change.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"transition {field} must be a non-empty string")
                values[field] = value.strip()
            normalized.append(
                {
                    "date": values["date"],
                    "from": values["from"],
                    "to": values["to"],
                    "title": values["title"],
                }
            )
        return normalized

    @staticmethod
    def _string_attribute(instance: object, name: str, default: str) -> str:
        value = getattr(instance, name, default)
        if isinstance(value, (str, int, float)):
            return str(value)
        return default

    @staticmethod
    def _normalize_priority(level: str) -> str:
        normalized = level.strip().lower()
        aliases = {
            "warning": "high",
            "warn": "high",
            "error": "critical",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in {"low", "normal", "high", "critical"} else "normal"


# ========================================
# 服务工厂
# ========================================


class NotificationServiceFactory:
    """通知服务工厂

    根据配置创建通知服务实例。
    """

    _email_service: EmailNotificationService | None = None
    _in_app_service: InAppNotificationService | None = None
    _alert_service: PolicyAlertService | None = None

    @classmethod
    def get_email_service(cls) -> EmailNotificationService:
        """获取邮件通知服务（单例）"""
        if cls._email_service is None:
            default_recipients = getattr(settings, "POLICY_ALERT_EMAILS", [])
            enabled = getattr(settings, "POLICY_EMAIL_NOTIFICATIONS_ENABLED", True)
            cls._email_service = EmailNotificationService(
                enabled=enabled, default_recipients=default_recipients
            )
        return cls._email_service

    @classmethod
    def get_in_app_service(cls) -> InAppNotificationService:
        """获取站内通知服务（单例）"""
        if cls._in_app_service is None:
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
    def reset(cls) -> None:
        """重置单例（主要用于测试）"""
        cls._email_service = None
        cls._in_app_service = None
        cls._alert_service = None
