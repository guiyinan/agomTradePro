"""
Alert Service - Infrastructure Layer

告警服务接口和实现，支持多种告警渠道。
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertResult:
    """告警结果"""
    success: bool
    channel: str
    level: AlertLevel
    message: str
    error: str | None = None


class AlertChannel(ABC):
    """告警渠道抽象基类"""

    @abstractmethod
    def send(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> AlertResult:
        """
        发送告警

        Args:
            level: 告警级别
            title: 标题
            message: 消息内容
            metadata: 额外元数据

        Returns:
            AlertResult: 告警结果
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查渠道是否可用"""
        pass

    def send_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> AlertResult:
        """
        兼容旧接口：send_alert -> send
        """
        return self.send(level=level, title=title, message=message, metadata=metadata)


class SlackAlertChannel(AlertChannel):
    """Slack 告警渠道"""

    def __init__(self, webhook_url: str):
        """
        初始化 Slack 告警渠道

        Args:
            webhook_url: Slack Webhook URL
        """
        self.webhook_url = webhook_url

    def send(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> AlertResult:
        """发送 Slack 告警"""
        try:
            # 颜色映射
            colors = {
                AlertLevel.INFO: "#36a64f",
                AlertLevel.WARNING: "#ff9800",
                AlertLevel.CRITICAL: "#ff0000",
            }

            # 构建 Slack 消息
            slack_message = {
                "attachments": [
                    {
                        "color": colors.get(level, "#36a64f"),
                        "title": title,
                        "text": message,
                        "footer": "AgomTradePro Policy Alert",
                        "ts": int(__import__("time").time())
                    }
                ]
            }

            # 添加元数据字段
            if metadata:
                fields = []
                for key, value in metadata.items():
                    fields.append({
                        "title": key,
                        "value": str(value),
                        "short": True
                    })
                if fields:
                    slack_message["attachments"][0]["fields"] = fields

            response = requests.post(
                self.webhook_url,
                json=slack_message,
                timeout=10
            )

            if response.status_code == 200:
                logger.info(f"Slack alert sent successfully: {title}")
                return AlertResult(
                    success=True,
                    channel="slack",
                    level=level,
                    message=message
                )
            else:
                error_msg = f"Slack API returned {response.status_code}"
                logger.error(f"Failed to send Slack alert: {error_msg}")
                return AlertResult(
                    success=False,
                    channel="slack",
                    level=level,
                    message=message,
                    error=error_msg
                )

        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
            return AlertResult(
                success=False,
                channel="slack",
                level=level,
                message=message,
                error=str(e)
            )

    def is_available(self) -> bool:
        """检查 Slack Webhook 是否可用"""
        try:
            if not self.webhook_url:
                return False
            return self.webhook_url.startswith("https://hooks.slack.com/")
        except Exception:
            return False


class EmailAlertChannel(AlertChannel):
    """邮件告警渠道"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_emails: list[str]
    ):
        """
        初始化邮件告警渠道

        Args:
            smtp_host: SMTP 服务器地址
            smtp_port: SMTP 端口
            username: 用户名
            password: 密码
            from_email: 发件人邮箱
            to_emails: 收件人邮箱列表
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_emails = to_emails

    def send(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> AlertResult:
        """发送邮件告警"""
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            # 构建邮件
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{level.value.upper()}] {title}"
            msg["From"] = self.from_email
            msg["To"] = ", ".join(self.to_emails)

            # 邮件正文
            email_body = f"""
            <html>
            <head></head>
            <body>
                <h2>{title}</h2>
                <p><strong>级别:</strong> {level.value.upper()}</p>
                <p><strong>时间:</strong> {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <hr>
                <pre>{message}</pre>
            </body>
            </html>
            """

            msg.attach(MIMEText(email_body, "html"))

            # 发送邮件
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Email alert sent successfully: {title}")
            return AlertResult(
                success=True,
                channel="email",
                level=level,
                message=message
            )

        except Exception as e:
            logger.error(f"Failed to send email alert: {e}", exc_info=True)
            return AlertResult(
                success=False,
                channel="email",
                level=level,
                message=message,
                error=str(e)
            )

    def is_available(self) -> bool:
        """检查邮件服务是否可用"""
        try:
            return all([
                self.smtp_host,
                self.smtp_port > 0,
                self.username,
                self.password,
                self.from_email,
                self.to_emails
            ])
        except Exception:
            return False


class ConsoleAlertChannel(AlertChannel):
    """控制台告警渠道（用于测试和开发）"""

    def send(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> AlertResult:
        """打印告警到控制台"""
        try:
            # 获取时间戳
            timestamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 根据级别选择颜色符号
            symbols = {
                AlertLevel.INFO: "📢",
                AlertLevel.WARNING: "⚠️",
                AlertLevel.CRITICAL: "🚨",
            }

            print(f"\n{symbols.get(level, '📢')} [{level.value.upper()}] {title}")
            print(f"时间: {timestamp}")
            print("-" * 50)
            print(message)
            if metadata:
                print("元数据:")
                for key, value in metadata.items():
                    print(f"  {key}: {value}")
            print("-" * 50)

            return AlertResult(
                success=True,
                channel="console",
                level=level,
                message=message
            )

        except Exception as e:
            logger.error(f"Failed to print alert: {e}")
            return AlertResult(
                success=False,
                channel="console",
                level=level,
                message=message,
                error=str(e)
            )

    def is_available(self) -> bool:
        """控制台始终可用"""
        return True


class MultiChannelAlertService:
    """
    多渠道告警服务

    支持同时发送告警到多个渠道
    """

    def __init__(self, channels: list[AlertChannel]):
        """
        初始化多渠道告警服务

        Args:
            channels: 告警渠道列表
        """
        self.channels = channels

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ) -> bool:
        """
        发送告警到所有可用渠道

        Args:
            level: 告警级别 (info/warning/critical)
            title: 标题
            message: 消息
            metadata: 元数据

        Returns:
            bool: 是否至少有一个渠道发送成功
        """
        # 转换 level
        try:
            alert_level = AlertLevel(level)
        except ValueError:
            logger.warning(f"Invalid alert level: {level}, using INFO")
            alert_level = AlertLevel.INFO

        results = []

        for channel in self.channels:
            if not channel.is_available():
                logger.warning(f"Channel {channel.__class__.__name__} is not available")
                continue

            try:
                result = channel.send(alert_level, title, message, metadata)
                results.append(result)
            except Exception as e:
                logger.error(
                    f"Failed to send alert via {channel.__class__.__name__}: {e}"
                )

        # 至少有一个成功即返回 True
        success_count = sum(1 for r in results if r.success)
        logger.info(f"Alert sent to {success_count}/{len(self.channels)} channels")

        return success_count > 0

    def add_channel(self, channel: AlertChannel) -> None:
        """添加告警渠道"""
        self.channels.append(channel)

    def remove_channel(self, channel_class: type) -> None:
        """移除指定类型的渠道"""
        self.channels = [c for c in self.channels if not isinstance(c, channel_class)]


def create_default_alert_service(
    slack_webhook: str | None = None,
    email_config: dict[str, Any] | None = None,
    use_console: bool = True
) -> MultiChannelAlertService:
    """
    创建默认的告警服务

    Args:
        slack_webhook: Slack Webhook URL
        email_config: 邮件配置字典
        use_console: 是否使用控制台输出（开发/测试用）

    Returns:
        MultiChannelAlertService: 告警服务实例
    """
    channels = []

    # 添加 Slack 渠道
    if slack_webhook:
        channels.append(SlackAlertChannel(slack_webhook))

    # 添加邮件渠道
    if email_config:
        channels.append(EmailAlertChannel(
            smtp_host=email_config.get("smtp_host", ""),
            smtp_port=email_config.get("smtp_port", 587),
            username=email_config.get("username", ""),
            password=email_config.get("password", ""),
            from_email=email_config.get("from_email", ""),
            to_emails=email_config.get("to_emails", [])
        ))

    # 添加控制台渠道（开发环境）
    if use_console:
        channels.append(ConsoleAlertChannel())

    return MultiChannelAlertService(channels)
