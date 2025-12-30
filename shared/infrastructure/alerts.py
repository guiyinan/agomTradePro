"""
Alert Service for AgomSAAF.

支持多种告警渠道：邮件、Slack、钉钉、企业微信等。
"""

import os
import smtplib
import json
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    """告警消息"""
    title: str
    content: str
    level: str = "INFO"  # INFO, WARNING, ERROR, CRITICAL
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.metadata is None:
            self.metadata = {}


class AlertChannel:
    """告警渠道基类"""

    def send(self, message: AlertMessage) -> bool:
        """发送告警消息"""
        raise NotImplementedError


class EmailAlertChannel(AlertChannel):
    """邮件告警渠道"""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: List[str],
        use_tls: bool = True
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    def send(self, message: AlertMessage) -> bool:
        """发送邮件告警"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = f"[{message.level}] {message.title}"
            msg['From'] = self.from_addr
            msg['To'] = ', '.join(self.to_addrs)

            # 构建邮件内容
            html_content = self._format_html(message)
            text_content = self._format_text(message)

            msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))

            # 发送邮件
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Email alert sent: {message.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False

    def _format_text(self, message: AlertMessage) -> str:
        """格式化纯文本内容"""
        lines = [
            f"级别: {message.level}",
            f"时间: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            message.content,
        ]

        if message.metadata:
            lines.append("")
            lines.append("详细信息:")
            for key, value in message.metadata.items():
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)

    def _format_html(self, message: AlertMessage) -> str:
        """格式化 HTML 内容"""
        # 根据级别设置颜色
        colors = {
            "INFO": "#2196F3",
            "WARNING": "#FF9800",
            "ERROR": "#F44336",
            "CRITICAL": "#D32F2F"
        }
        color = colors.get(message.level, "#666666")

        # 构建元数据表格
        metadata_rows = ""
        if message.metadata:
            for key, value in message.metadata.items():
                metadata_rows += f"<tr><td><b>{key}</b></td><td>{value}</td></tr>"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: {color}; color: white; padding: 15px; border-radius: 5px 5px 0 0; }}
                .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .metadata {{ margin-top: 20px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                tr:last-child td {{ border-bottom: none; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>{message.title}</h2>
                    <p>级别: {message.level} | 时间: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="content">
                    <p>{message.content.replace(chr(10), '<br>')}</p>
                    {f'<div class="metadata"><table>{metadata_rows}</table></div>' if metadata_rows else ''}
                </div>
            </div>
        </body>
        </html>
        """
        return html


class SlackAlertChannel(AlertChannel):
    """Slack 告警渠道"""

    def __init__(self, webhook_url: str, channel: Optional[str] = None, username: str = "AgomSAAF Bot"):
        self.webhook_url = webhook_url
        self.channel = channel
        self.username = username

    def send(self, message: AlertMessage) -> bool:
        """发送 Slack 告警"""
        try:
            # 根据级别设置颜色
            colors = {
                "INFO": "#2196F3",
                "WARNING": "#FF9800",
                "ERROR": "#F44336",
                "CRITICAL": "#D32F2F"
            }
            color = colors.get(message.level, "#666666")

            # 构建消息
            payload = {
                "username": self.username,
                "attachments": [
                    {
                        "color": color,
                        "title": message.title,
                        "text": message.content,
                        "fields": [
                            {
                                "title": "级别",
                                "value": message.level,
                                "short": True
                            },
                            {
                                "title": "时间",
                                "value": message.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                                "short": True
                            }
                        ],
                        "footer": "AgomSAAF Alert System",
                        "ts": int(message.timestamp.timestamp())
                    }
                ]
            }

            if self.channel:
                payload["channel"] = self.channel

            # 添加元数据
            if message.metadata:
                for key, value in message.metadata.items():
                    payload["attachments"][0]["fields"].append({
                        "title": key,
                        "value": str(value),
                        "short": True
                    })

            # 发送请求
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()

            logger.info(f"Slack alert sent: {message.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False


class DingTalkAlertChannel(AlertChannel):
    """钉钉告警渠道"""

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret

    def send(self, message: AlertMessage) -> bool:
        """发送钉钉告警"""
        try:
            # 构建消息
            text = f"### {message.title}\n\n"
            text += f"**级别**: {message.level}\n"
            text += f"**时间**: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            text += f"{message.content}\n"

            if message.metadata:
                text += "\n**详细信息**:\n"
                for key, value in message.metadata.items():
                    text += f"- {key}: {value}\n"

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": message.title,
                    "text": text
                }
            }

            # 发送请求
            headers = {"Content-Type": "application/json;charset=utf-8"}
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            logger.info(f"DingTalk alert sent: {message.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to send DingTalk alert: {e}")
            return False


class WeChatWorkAlertChannel(AlertChannel):
    """企业微信告警渠道"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, message: AlertMessage) -> bool:
        """发送企业微信告警"""
        try:
            # 构建消息
            content = f"### {message.title}\n"
            content += f"级别: {message.level}\n"
            content += f"时间: {message.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            content += f"{message.content}\n"

            if message.metadata:
                content += "\n详细信息:\n"
                for key, value in message.metadata.items():
                    content += f"{key}: {value}\n"

            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": content
                }
            }

            # 发送请求
            headers = {"Content-Type": "application/json;charset=utf-8"}
            response = requests.post(
                self.webhook_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=10
            )
            response.raise_for_status()

            logger.info(f"WeChat Work alert sent: {message.title}")
            return True

        except Exception as e:
            logger.error(f"Failed to send WeChat Work alert: {e}")
            return False


class AlertService:
    """告警服务

    支持多渠道发送告警消息。
    """

    def __init__(self, channels: Optional[List[AlertChannel]] = None):
        self.channels = channels or []
        self.logger = logging.getLogger(__name__)

    def add_channel(self, channel: AlertChannel):
        """添加告警渠道"""
        self.channels.append(channel)

    def send(self, message: AlertMessage) -> Dict[str, bool]:
        """发送告警到所有渠道"""
        results = {}
        for i, channel in enumerate(self.channels):
            channel_name = channel.__class__.__name__
            try:
                success = channel.send(message)
                results[channel_name] = success
            except Exception as e:
                self.logger.error(f"Channel {channel_name} failed: {e}")
                results[channel_name] = False

        # 记录发送结果
        success_count = sum(1 for v in results.values() if v)
        self.logger.info(f"Alert sent to {success_count}/{len(self.channels)} channels")

        return results

    def send_info(self, title: str, content: str, **kwargs) -> Dict[str, bool]:
        """发送 INFO 级别告警"""
        message = AlertMessage(title=title, content=content, level="INFO", **kwargs)
        return self.send(message)

    def send_warning(self, title: str, content: str, **kwargs) -> Dict[str, bool]:
        """发送 WARNING 级别告警"""
        message = AlertMessage(title=title, content=content, level="WARNING", **kwargs)
        return self.send(message)

    def send_error(self, title: str, content: str, **kwargs) -> Dict[str, bool]:
        """发送 ERROR 级别告警"""
        message = AlertMessage(title=title, content=content, level="ERROR", **kwargs)
        return self.send(message)

    def send_critical(self, title: str, content: str, **kwargs) -> Dict[str, bool]:
        """发送 CRITICAL 级别告警"""
        message = AlertMessage(title=title, content=content, level="CRITICAL", **kwargs)
        return self.send(message)


# 全局告警服务实例
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """获取全局告警服务实例"""
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()

        # 从环境变量配置告警渠道
        # 邮件告警
        smtp_host = os.getenv("ALERT_SMTP_HOST")
        if smtp_host:
            channel = EmailAlertChannel(
                smtp_host=smtp_host,
                smtp_port=int(os.getenv("ALERT_SMTP_PORT", "587")),
                username=os.getenv("ALERT_SMTP_USERNAME", ""),
                password=os.getenv("ALERT_SMTP_PASSWORD", ""),
                from_addr=os.getenv("ALERT_EMAIL_FROM", ""),
                to_addrs=os.getenv("ALERT_EMAIL_TO", "").split(","),
            )
            _alert_service.add_channel(channel)

        # Slack 告警
        slack_webhook = os.getenv("ALERT_SLACK_WEBHOOK")
        if slack_webhook:
            channel = SlackAlertChannel(webhook_url=slack_webhook)
            _alert_service.add_channel(channel)

        # 钉钉告警
        dingtalk_webhook = os.getenv("ALERT_DINGTALK_WEBHOOK")
        if dingtalk_webhook:
            channel = DingTalkAlertChannel(webhook_url=dingtalk_webhook)
            _alert_service.add_channel(channel)

        # 企业微信告警
        wechat_webhook = os.getenv("ALERT_WECHAT_WEBHOOK")
        if wechat_webhook:
            channel = WeChatWorkAlertChannel(webhook_url=wechat_webhook)
            _alert_service.add_channel(channel)

    return _alert_service


# 便捷函数
def send_alert(title: str, content: str, level: str = "INFO", **kwargs) -> Dict[str, bool]:
    """发送告警（便捷函数）"""
    service = get_alert_service()
    message = AlertMessage(title=title, content=content, level=level, **kwargs)
    return service.send(message)
