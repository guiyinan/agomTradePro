"""
Domain Layer - Protocol Interfaces for Policy

本文件定义Policy模块的Protocol接口，用于依赖注入和解耦。
"""

from typing import List, Optional, Protocol

from .entities import AIClassificationResult, PolicyEvent, PolicyLevel, RSSItem


class NotificationChannel:
    """通知渠道"""
    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


class NotificationMessage:
    """通知消息值对象"""
    title: str
    content: str
    channel: str
    priority: str  # low, normal, high, critical
    recipients: list[str]
    metadata: dict

    def __init__(
        self,
        title: str,
        content: str,
        channel: str = NotificationChannel.IN_APP,
        priority: str = "normal",
        recipients: list[str] | None = None,
        metadata: dict | None = None
    ):
        self.title = title
        self.content = content
        self.channel = channel
        self.priority = priority
        self.recipients = recipients or []
        self.metadata = metadata or {}


class NotificationServicePort(Protocol):
    """通知服务协议

    定义通知服务的抽象接口，用于依赖注入。
    Infrastructure 层提供具体实现（邮件、站内信、Webhook等）。
    """

    def send(self, message: NotificationMessage) -> bool:
        """发送通知

        Args:
            message: 通知消息

        Returns:
            bool: 发送是否成功
        """
        ...

    def send_batch(self, messages: list[NotificationMessage]) -> dict:
        """批量发送通知

        Args:
            messages: 通知消息列表

        Returns:
            dict: {"success": int, "failed": int, "errors": List[str]}
        """
        ...


class PolicyAlertServicePort(Protocol):
    """政策告警服务协议

    专门用于政策相关告警的服务协议。
    """

    def send_policy_alert(
        self,
        level: PolicyLevel,
        event: PolicyEvent,
        status: object
    ) -> bool:
        """发送政策档位告警

        Args:
            level: 政策档位
            event: 政策事件
            status: 政策状态对象

        Returns:
            bool: 发送是否成功
        """
        ...

    def send_transition_summary(self, changes: list[dict]) -> bool:
        """发送档位变更摘要

        Args:
            changes: 变更列表

        Returns:
            bool: 发送是否成功
        """
        ...

    def send_sla_alert(self, p23_count: int, normal_count: int) -> bool:
        """发送SLA超时告警

        Args:
            p23_count: P2/P3超时数量
            normal_count: 普通超时数量

        Returns:
            bool: 发送是否成功
        """
        ...


class PolicyClassifierProtocol(Protocol):
    """政策分类器协议"""

    def classify_rss_item(
        self,
        item: RSSItem,
        content: str | None = None
    ) -> AIClassificationResult:
        """
        对RSS条目进行AI分类和结构化提取

        Args:
            item: RSS条目
            content: 可选的完整内容（如果extract_content=True）

        Returns:
            AIClassificationResult: 分类结果
        """
        ...

    def batch_classify(
        self,
        items: list[tuple[RSSItem, str | None]]
    ) -> list[AIClassificationResult]:
        """
        批量分类

        Args:
            items: (RSS条目, 可选内容) 的列表

        Returns:
            List[AIClassificationResult]: 分类结果列表
        """
        ...
