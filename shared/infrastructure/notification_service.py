"""
Unified Notification Service

统一通知服务 - Infrastructure 层

支持多种通知通道：
1. 邮件通知 (Email)
2. 站内通知 (In-App)
3. 告警通知 (Alert)

功能特性：
- 失败重试机制
- 告警触发
- 通知历史记录
- 多通道并行发送
"""

import logging
import smtplib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail as django_send_mail
from django.utils import timezone

from core.exceptions import AgomTradeProException, ExternalServiceError
from shared.infrastructure.resilience import MaxRetriesExceeded, retry_on_error

logger = logging.getLogger(__name__)


# ============================================================================
# Enums and Constants
# ============================================================================

class NotificationChannel(Enum):
    """通知通道类型"""
    EMAIL = "email"
    IN_APP = "in_app"
    ALERT = "alert"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationPriority(Enum):
    """通知优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(Enum):
    """通知状态"""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(frozen=True)
class NotificationRecipient:
    """通知接收者"""
    user_id: int | None = None
    email: str | None = None
    phone: str | None = None
    name: str = ""


@dataclass
class NotificationMessage:
    """通知消息"""
    subject: str
    body: str
    html_body: str | None = None
    priority: NotificationPriority = NotificationPriority.NORMAL
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    correlation_id: str | None = None


@dataclass
class NotificationResult:
    """通知发送结果"""
    success: bool
    channel: NotificationChannel
    recipient: NotificationRecipient
    status: NotificationStatus
    error_message: str | None = None
    sent_at: datetime | None = None
    retry_count: int = 0
    notification_id: str | None = None


@dataclass
class NotificationConfig:
    """通知配置"""
    max_retries: int = 3
    initial_retry_delay: float = 1.0
    retry_backoff_factor: float = 2.0
    max_retry_delay: float = 60.0
    timeout_seconds: int = 30
    enable_retry: bool = True
    enable_alert_on_failure: bool = True
    alert_threshold: int = 3  # 连续失败多少次触发告警


# ============================================================================
# Exceptions
# ============================================================================

class NotificationError(AgomTradeProException):
    """通知基础异常"""
    default_message = "通知发送失败"
    default_code = "NOTIFICATION_ERROR"
    default_status_code = 503


class EmailSendError(NotificationError):
    """邮件发送失败"""
    default_message = "邮件发送失败"
    default_code = "EMAIL_SEND_ERROR"


class InAppNotificationError(NotificationError):
    """站内通知失败"""
    default_message = "站内通知失败"
    default_code = "IN_APP_NOTIFICATION_ERROR"


class NotificationRateLimitExceeded(NotificationError):
    """通知频率限制"""
    default_message = "通知频率过高，已限流"
    default_code = "RATE_LIMIT_EXCEEDED"
    default_status_code = 429


# ============================================================================
# Abstract Channel Interface
# ============================================================================

class NotificationChannelInterface(ABC):
    """通知通道抽象接口"""

    @abstractmethod
    def send(
        self,
        message: NotificationMessage,
        recipient: NotificationRecipient,
        config: NotificationConfig
    ) -> NotificationResult:
        """
        发送通知

        Args:
            message: 通知消息
            recipient: 接收者
            config: 通知配置

        Returns:
            NotificationResult: 发送结果
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查通道是否可用"""
        pass

    @abstractmethod
    def get_channel_type(self) -> NotificationChannel:
        """获取通道类型"""
        pass

    def validate_recipient(self, recipient: NotificationRecipient) -> bool:
        """验证接收者是否有效"""
        return True


# ============================================================================
# Email Notification Channel
# ============================================================================

class EmailNotificationChannel(NotificationChannelInterface):
    """
    邮件通知通道

    使用 Django 的邮件后端，支持 SMTP 和其他后端。
    支持失败重试和告警。
    """

    def __init__(
        self,
        from_email: str | None = None,
        use_html: bool = True,
        reply_to: list[str] | None = None
    ):
        """
        初始化邮件通知通道

        Args:
            from_email: 发件人邮箱（默认使用 settings.DEFAULT_FROM_EMAIL）
            use_html: 是否使用 HTML 格式
            reply_to: 回复邮箱列表
        """
        self.from_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@agomtradepro.com")
        self.use_html = use_html
        self.reply_to = reply_to or []

        # 统计计数器
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None

    def get_channel_type(self) -> NotificationChannel:
        return NotificationChannel.EMAIL

    def is_available(self) -> bool:
        """检查邮件服务是否可用"""
        try:
            # 检查基本配置
            email_backend = getattr(settings, "EMAIL_BACKEND", "")
            email_host = getattr(settings, "EMAIL_HOST", "")

            # 使用控制台后端时始终可用（开发环境）
            if "console" in email_backend.lower():
                return True

            # 使用 SMTP 后端时检查主机配置
            return bool(email_host)

        except Exception as e:
            logger.error(f"检查邮件服务可用性失败: {e}")
            return False

    def validate_recipient(self, recipient: NotificationRecipient) -> bool:
        """验证接收者邮箱是否有效"""
        if not recipient.email:
            return False

        # 基本邮箱格式验证
        email = recipient.email.strip()
        if "@" not in email or "." not in email.split("@")[-1]:
            return False

        return True

    @retry_on_error(
        max_retries=2,
        initial_delay=1.0,
        backoff_factor=2.0,
        exceptions=(smtplib.SMTPException, ConnectionError, OSError),
    )
    def _send_email(
        self,
        subject: str,
        body: str,
        recipient_email: str,
        html_body: str | None = None
    ) -> bool:
        """
        实际发送邮件（带重试装饰器）

        Args:
            subject: 邮件主题
            body: 纯文本内容
            recipient_email: 收件人邮箱
            html_body: HTML 内容（可选）

        Returns:
            bool: 是否发送成功
        """
        recipient_list = [recipient_email]

        if html_body and self.use_html:
            # 使用 HTML 邮件
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.from_email
            message["To"] = recipient_email

            if self.reply_to:
                message["Reply-To"] = ", ".join(self.reply_to)

            # 添加纯文本部分
            text_part = MIMEText(body, "plain", "utf-8")
            message.attach(text_part)

            # 添加 HTML 部分
            html_part = MIMEText(html_body, "html", "utf-8")
            message.attach(html_part)

            # 发送
            with smtplib.SMTP(
                getattr(settings, "EMAIL_HOST", "localhost"),
                getattr(settings, "EMAIL_PORT", 25)
            ) as server:
                if getattr(settings, "EMAIL_USE_TLS", False):
                    server.starttls()

                if getattr(settings, "EMAIL_HOST_USER", ""):
                    server.login(
                        getattr(settings, "EMAIL_HOST_USER", ""),
                        getattr(settings, "EMAIL_HOST_PASSWORD", "")
                    )

                server.send_message(message)
        else:
            # 使用 Django send_mail
            django_send_mail(
                subject=subject,
                message=body,
                from_email=self.from_email,
                recipient_list=recipient_list,
                fail_silently=False,
                html_message=html_body if self.use_html else None
            )

        return True

    def send(
        self,
        message: NotificationMessage,
        recipient: NotificationRecipient,
        config: NotificationConfig
    ) -> NotificationResult:
        """
        发送邮件通知

        Args:
            message: 通知消息
            recipient: 接收者
            config: 通知配置

        Returns:
            NotificationResult: 发送结果
        """
        # 验证接收者
        if not self.validate_recipient(recipient):
            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message=f"无效的收件人邮箱: {recipient.email}"
            )

        # 检查通道可用性
        if not self.is_available():
            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message="邮件服务不可用"
            )

        # 检查频率限制
        rate_limit_key = f"email_rate_limit:{recipient.email}"
        if cache.get(rate_limit_key):
            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message="邮件发送频率过高，已限流"
            )

        # 构建邮件内容
        subject = self._format_subject(message)
        body = self._format_body(message)
        html_body = message.html_body or self._format_html_body(message)

        # 尝试发送
        retry_count = 0
        last_error = None

        for attempt in range(config.max_retries + 1):
            try:
                self._send_email(subject, body, recipient.email, html_body)

                # 发送成功
                self._success_count += 1
                self._failure_count = 0

                # 设置频率限制（每分钟最多 10 封邮件）
                cache.set(rate_limit_key, 1, timeout=6)

                return NotificationResult(
                    success=True,
                    channel=self.get_channel_type(),
                    recipient=recipient,
                    status=NotificationStatus.SENT,
                    sent_at=timezone.now(),
                    retry_count=retry_count
                )

            except MaxRetriesExceeded as e:
                last_error = str(e)
                retry_count = config.max_retries

            except Exception as e:
                last_error = str(e)
                retry_count = attempt

                if attempt < config.max_retries:
                    delay = min(
                        config.initial_retry_delay * (config.retry_backoff_factor ** attempt),
                        config.max_retry_delay
                    )
                    logger.warning(
                        f"邮件发送失败 (尝试 {attempt + 1}/{config.max_retries}): {e}, "
                        f"{delay:.1f}秒后重试..."
                    )
                    import time
                    time.sleep(delay)

        # 所有重试均失败
        self._failure_count += 1
        self._last_failure_time = timezone.now()

        logger.error(
            f"邮件发送失败 (已重试 {retry_count} 次): {last_error}"
        )

        return NotificationResult(
            success=False,
            channel=self.get_channel_type(),
            recipient=recipient,
            status=NotificationStatus.FAILED,
            error_message=last_error,
            retry_count=retry_count
        )

    def _format_subject(self, message: NotificationMessage) -> str:
        """格式化邮件主题"""
        priority_prefix = {
            NotificationPriority.LOW: "",
            NotificationPriority.NORMAL: "",
            NotificationPriority.HIGH: "[重要]",
            NotificationPriority.URGENT: "[紧急]",
        }
        prefix = priority_prefix.get(message.priority, "")
        return f"{prefix} {message.subject}".strip()

    def _format_body(self, message: NotificationMessage) -> str:
        """格式化纯文本邮件内容"""
        lines = [
            message.subject,
            "=" * len(message.subject),
            "",
            message.body,
        ]

        if message.metadata:
            lines.extend([
                "",
                "详细信息:",
            ])
            for key, value in message.metadata.items():
                lines.append(f"  {key}: {value}")

        lines.extend([
            "",
            f"发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 50,
        ])

        return "\n".join(lines)

    def _format_html_body(self, message: NotificationMessage) -> str:
        """格式化 HTML 邮件内容"""
        priority_color = {
            NotificationPriority.LOW: "#6c757d",
            NotificationPriority.NORMAL: "#007bff",
            NotificationPriority.HIGH: "#ffc107",
            NotificationPriority.URGENT: "#dc3545",
        }
        color = priority_color.get(message.priority, "#007bff")

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background-color: {color}; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .footer {{ background-color: #f8f9fa; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; }}
                .metadata {{ background-color: #f8f9fa; padding: 15px; margin-top: 20px; border-radius: 5px; }}
                .label {{ font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>{message.subject}</h2>
            </div>
            <div class="content">
                <p>{message.body.replace(chr(10), '<br>')}</p>
        """

        if message.metadata:
            html += '<div class="metadata"><h3>详细信息</h3>'
            for key, value in message.metadata.items():
                html += f'<p><span class="label">{key}:</span> {value}</p>'
            html += '</div>'

        html += f"""
            </div>
            <div class="footer">
                <p>发送时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p>AgomTradePro - 自动发送，请勿回复</p>
            </div>
        </body>
        </html>
        """

        return html

    def get_statistics(self) -> dict[str, Any]:
        """获取统计信息"""
        return {
            "channel": "email",
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_failure_time": self._last_failure_time.isoformat() if self._last_failure_time else None,
            "is_available": self.is_available(),
        }


# ============================================================================
# In-App Notification Channel
# ============================================================================

class InAppNotificationChannel(NotificationChannelInterface):
    """
    站内通知通道

    将通知保存到数据库，用户在系统内查看。
    需要创建 NotificationModel 来存储通知。
    """

    def __init__(self, model_class=None):
        """
        初始化站内通知通道

        Args:
            model_class: 存储 Notification 的 Django Model 类
        """
        self.model_class = model_class
        self._failure_count = 0
        self._success_count = 0

    def get_channel_type(self) -> NotificationChannel:
        return NotificationChannel.IN_APP

    def is_available(self) -> bool:
        """检查站内通知是否可用"""
        try:
            # 检查模型是否已配置
            if self.model_class is None:
                # 尝试动态导入
                try:
                    from apps.notifications.infrastructure.models import InAppNotificationModel
                    self.model_class = InAppNotificationModel
                except ImportError:
                    logger.warning("站内通知模型未配置")
                    return False

            return True

        except Exception as e:
            logger.error(f"检查站内通知可用性失败: {e}")
            return False

    def validate_recipient(self, recipient: NotificationRecipient) -> bool:
        """验证接收者是否有效"""
        return recipient.user_id is not None

    def send(
        self,
        message: NotificationMessage,
        recipient: NotificationRecipient,
        config: NotificationConfig
    ) -> NotificationResult:
        """
        发送站内通知

        Args:
            message: 通知消息
            recipient: 接收者
            config: 通知配置

        Returns:
            NotificationResult: 发送结果
        """
        # 验证接收者
        if not self.validate_recipient(recipient):
            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message=f"无效的接收者 ID: {recipient.user_id}"
            )

        # 检查通道可用性
        if not self.is_available():
            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message="站内通知服务不可用"
            )

        try:
            # 创建通知记录
            notification = self.model_class._default_manager.create(
                user_id=recipient.user_id,
                title=message.subject,
                content=message.body,
                html_content=message.html_body,
                priority=message.priority.value,
                metadata=message.metadata,
                tags=message.tags,
                correlation_id=message.correlation_id,
                is_read=False,
                created_at=timezone.now(),
            )

            self._success_count += 1

            return NotificationResult(
                success=True,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.SENT,
                sent_at=timezone.now(),
                notification_id=str(notification.id)
            )

        except Exception as e:
            self._failure_count += 1
            logger.error(f"创建站内通知失败: {e}", exc_info=True)

            return NotificationResult(
                success=False,
                channel=self.get_channel_type(),
                recipient=recipient,
                status=NotificationStatus.FAILED,
                error_message=str(e)
            )


# ============================================================================
# Alert Notification Channel
# ============================================================================

class AlertNotificationChannel(NotificationChannelInterface):
    """
    告警通知通道

    使用 alert_service 发送告警到 Slack、邮件等渠道。
    """

    def __init__(self):
        """初始化告警通知通道"""
        from shared.infrastructure.alert_service import (
            AlertLevel,
            ConsoleAlertChannel,
            MultiChannelAlertService,
        )

        # 创建告警服务
        self.alert_service = MultiChannelAlertService([
            ConsoleAlertChannel()  # 默认使用控制台
        ])

        # 尝试添加其他通道
        self._setup_channels()

    def _setup_channels(self):
        """设置告警通道"""
        try:
            # 尝试添加 Slack
            slack_webhook = getattr(settings, "SLACK_WEBHOOK_URL", None)
            if slack_webhook:
                from shared.infrastructure.alert_service import SlackAlertChannel
                self.alert_service.add_channel(SlackAlertChannel(slack_webhook))
        except Exception as e:
            logger.warning(f"无法添加 Slack 告警通道: {e}")

    def get_channel_type(self) -> NotificationChannel:
        return NotificationChannel.ALERT

    def is_available(self) -> bool:
        """检查告警通道是否可用"""
        return True  # ConsoleAlertChannel 始终可用

    def validate_recipient(self, recipient: NotificationRecipient) -> bool:
        """告警不需要验证接收者"""
        return True

    def send(
        self,
        message: NotificationMessage,
        recipient: NotificationRecipient,
        config: NotificationConfig
    ) -> NotificationResult:
        """
        发送告警通知

        Args:
            message: 通知消息
            recipient: 接收者（告警通常不需要）
            config: 通知配置

        Returns:
            NotificationResult: 发送结果
        """
        from shared.infrastructure.alert_service import AlertLevel

        # 将优先级映射到告警级别
        level_mapping = {
            NotificationPriority.LOW: AlertLevel.INFO,
            NotificationPriority.NORMAL: AlertLevel.INFO,
            NotificationPriority.HIGH: AlertLevel.WARNING,
            NotificationPriority.URGENT: AlertLevel.CRITICAL,
        }

        alert_level = level_mapping.get(message.priority, AlertLevel.INFO)

        # 发送告警
        success = self.alert_service.send_alert(
            level=alert_level.value,
            title=message.subject,
            message=message.body,
            metadata=message.metadata
        )

        return NotificationResult(
            success=success,
            channel=self.get_channel_type(),
            recipient=recipient,
            status=NotificationStatus.SENT if success else NotificationStatus.FAILED,
            sent_at=timezone.now() if success else None
        )


# ============================================================================
# Unified Notification Service
# ============================================================================

class UnifiedNotificationService:
    """
    统一通知服务

    整合多种通知通道，提供统一的发送接口。
    支持失败重试、告警触发和通知历史记录。
    """

    def __init__(
        self,
        channels: list[NotificationChannelInterface] | None = None,
        config: NotificationConfig | None = None
    ):
        """
        初始化统一通知服务

        Args:
            channels: 通知通道列表（None 则使用默认通道）
            config: 通知配置
        """
        self.config = config or NotificationConfig()
        self.channels: list[NotificationChannelInterface] = []

        # 注册通道
        if channels:
            self.channels.extend(channels)
        else:
            self._setup_default_channels()

        # 失败计数器（用于告警触发）
        self._channel_failures: dict[str, int] = {}

    def _setup_default_channels(self):
        """设置默认通知通道"""
        # 邮件通道
        self.channels.append(EmailNotificationChannel())

        # 站内通知通道
        self.channels.append(InAppNotificationChannel())

        # 告警通道
        self.channels.append(AlertNotificationChannel())

    def add_channel(self, channel: NotificationChannelInterface) -> None:
        """添加通知通道"""
        self.channels.append(channel)

    def remove_channel(self, channel_type: NotificationChannel) -> None:
        """移除指定类型的通道"""
        self.channels = [
            ch for ch in self.channels
            if ch.get_channel_type() != channel_type
        ]

    def send(
        self,
        message: NotificationMessage | str,
        recipients: NotificationRecipient | list[NotificationRecipient],
        channels: list[NotificationChannel] | None = None
    ) -> list[NotificationResult]:
        """
        发送通知

        Args:
            message: 通知消息（或纯文本）
            recipients: 接收者（单个或列表）
            channels: 指定通道（None 则使用所有通道）

        Returns:
            List[NotificationResult]: 发送结果列表
        """
        # 标准化消息
        if isinstance(message, str):
            message = NotificationMessage(
                subject=message,
                body=message
            )

        # 标准化接收者列表
        if isinstance(recipients, NotificationRecipient):
            recipients = [recipients]

        # 确定使用的通道
        target_channels = self.channels
        if channels:
            target_channels = [
                ch for ch in self.channels
                if ch.get_channel_type() in channels
            ]

        # 发送通知
        results = []

        for channel in target_channels:
            for recipient in recipients:
                try:
                    result = channel.send(message, recipient, self.config)
                    results.append(result)

                    # 处理失败
                    if not result.success:
                        self._handle_send_failure(channel, result)

                except Exception as e:
                    logger.error(
                        f"发送通知失败: channel={channel.get_channel_type().value}, "
                        f"recipient={recipient.email or recipient.user_id}, error={e}",
                        exc_info=True
                    )

                    results.append(NotificationResult(
                        success=False,
                        channel=channel.get_channel_type(),
                        recipient=recipient,
                        status=NotificationStatus.FAILED,
                        error_message=str(e)
                    ))

        return results

    def send_email(
        self,
        subject: str,
        body: str,
        recipients: str | list[str],
        html_body: str | None = None,
        priority: NotificationPriority = NotificationPriority.NORMAL
    ) -> list[NotificationResult]:
        """
        发送邮件通知（便捷方法）

        Args:
            subject: 邮件主题
            body: 邮件内容
            recipients: 收件人邮箱（单个或列表）
            html_body: HTML 内容
            priority: 优先级

        Returns:
            List[NotificationResult]: 发送结果列表
        """
        # 标准化收件人
        if isinstance(recipients, str):
            recipients = [recipients]

        # 构建接收者列表
        recipient_list = [
            NotificationRecipient(email=email)
            for email in recipients
        ]

        # 构建消息
        message = NotificationMessage(
            subject=subject,
            body=body,
            html_body=html_body,
            priority=priority
        )

        # 发送
        return self.send(
            message=message,
            recipients=recipient_list,
            channels=[NotificationChannel.EMAIL]
        )

    def send_in_app(
        self,
        user_id: int,
        title: str,
        content: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None
    ) -> NotificationResult:
        """
        发送站内通知（便捷方法）

        Args:
            user_id: 用户 ID
            title: 标题
            content: 内容
            priority: 优先级
            metadata: 元数据

        Returns:
            NotificationResult: 发送结果
        """
        message = NotificationMessage(
            subject=title,
            body=content,
            priority=priority,
            metadata=metadata or {}
        )

        recipient = NotificationRecipient(user_id=user_id)

        results = self.send(
            message=message,
            recipients=recipient,
            channels=[NotificationChannel.IN_APP]
        )

        return results[0] if results else NotificationResult(
            success=False,
            channel=NotificationChannel.IN_APP,
            recipient=recipient,
            status=NotificationStatus.FAILED,
            error_message="未配置站内通知通道"
        )

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
        metadata: dict[str, Any] | None = None
    ) -> NotificationResult:
        """
        发送告警通知（便捷方法）

        Args:
            title: 告警标题
            message: 告警消息
            level: 告警级别 (info/warning/critical)
            metadata: 元数据

        Returns:
            NotificationResult: 发送结果
        """
        # 将告警级别映射到优先级
        priority_mapping = {
            "info": NotificationPriority.LOW,
            "warning": NotificationPriority.NORMAL,
            "error": NotificationPriority.HIGH,
            "critical": NotificationPriority.URGENT,
        }

        priority = priority_mapping.get(level, NotificationPriority.NORMAL)

        notification_message = NotificationMessage(
            subject=title,
            body=message,
            priority=priority,
            metadata=metadata or {}
        )

        results = self.send(
            message=notification_message,
            recipients=NotificationRecipient(),  # 告警不需要特定接收者
            channels=[NotificationChannel.ALERT]
        )

        return results[0] if results else NotificationResult(
            success=False,
            channel=NotificationChannel.ALERT,
            recipient=NotificationRecipient(),
            status=NotificationStatus.FAILED,
            error_message="未配置告警通道"
        )

    def _handle_send_failure(
        self,
        channel: NotificationChannelInterface,
        result: NotificationResult
    ) -> None:
        """
        处理发送失败

        Args:
            channel: 通知通道
            result: 发送结果
        """
        channel_type = channel.get_channel_type().value
        self._channel_failures[channel_type] = self._channel_failures.get(channel_type, 0) + 1

        # 检查是否需要触发告警
        if self.config.enable_alert_on_failure:
            failure_count = self._channel_failures[channel_type]

            if failure_count >= self.config.alert_threshold:
                logger.critical(
                    f"通知通道 {channel_type} 连续失败 {failure_count} 次，"
                    f"已达到告警阈值"
                )

                # 发送告警
                try:
                    self.send_alert(
                        title=f"通知通道故障: {channel_type}",
                        message=f"通知通道 {channel_type} 连续失败 {failure_count} 次，请检查。",
                        level="critical",
                        metadata={
                            "channel": channel_type,
                            "failure_count": failure_count,
                            "last_error": result.error_message,
                        }
                    )

                    # 重置计数
                    self._channel_failures[channel_type] = 0

                except Exception as e:
                    logger.error(f"发送通知通道故障告警失败: {e}")

    def get_service_status(self) -> dict[str, Any]:
        """获取服务状态"""
        return {
            "channels": [
                {
                    "type": ch.get_channel_type().value,
                    "available": ch.is_available(),
                }
                for ch in self.channels
            ],
            "config": {
                "max_retries": self.config.max_retries,
                "enable_alert_on_failure": self.config.enable_alert_on_failure,
                "alert_threshold": self.config.alert_threshold,
            },
            "failures": self._channel_failures,
        }


# ============================================================================
# Global Service Instance
# ============================================================================

_notification_service: UnifiedNotificationService | None = None


def get_notification_service() -> UnifiedNotificationService:
    """获取全局通知服务单例"""
    global _notification_service

    if _notification_service is None:
        _notification_service = UnifiedNotificationService()

    return _notification_service


def send_notification(
    message: NotificationMessage | str,
    recipients: NotificationRecipient | list[NotificationRecipient],
    channels: list[NotificationChannel] | None = None
) -> list[NotificationResult]:
    """
    发送通知（便捷函数）

    Args:
        message: 通知消息
        recipients: 接收者
        channels: 通知通道

    Returns:
        List[NotificationResult]: 发送结果列表
    """
    service = get_notification_service()
    return service.send(message, recipients, channels)


def send_email_notification(
    subject: str,
    body: str,
    recipients: str | list[str],
    html_body: str | None = None
) -> list[NotificationResult]:
    """
    发送邮件通知（便捷函数）

    Args:
        subject: 邮件主题
        body: 邮件内容
        recipients: 收件人
        html_body: HTML 内容

    Returns:
        List[NotificationResult]: 发送结果列表
    """
    service = get_notification_service()
    return service.send_email(subject, body, recipients, html_body)


def send_alert_notification(
    title: str,
    message: str,
    level: str = "warning"
) -> NotificationResult:
    """
    发送告警通知（便捷函数）

    Args:
        title: 告警标题
        message: 告警消息
        level: 告警级别

    Returns:
        NotificationResult: 发送结果
    """
    service = get_notification_service()
    return service.send_alert(title, message, level)
