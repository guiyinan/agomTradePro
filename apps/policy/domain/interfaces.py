"""
Domain Layer - Protocol Interfaces for Policy

本文件定义Policy模块的Protocol接口，用于依赖注入和解耦。
"""

from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from .entities import AIClassificationResult, PolicyEvent, PolicyLevel, RSSItem


class NotificationChannel:
    """通知渠道"""

    EMAIL = "email"
    IN_APP = "in_app"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class NotificationMessage:
    """通知消息值对象"""

    title: str
    content: str
    channel: str = NotificationChannel.IN_APP
    priority: str = "normal"
    recipients: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip() or len(self.title) > 200:
            raise ValueError("notification title must contain 1-200 characters")
        if not self.content.strip():
            raise ValueError("notification content is required")
        if self.channel not in {
            NotificationChannel.EMAIL,
            NotificationChannel.IN_APP,
            NotificationChannel.WEBHOOK,
        }:
            raise ValueError("unsupported notification channel")
        if self.priority not in {"low", "normal", "high", "critical"}:
            raise ValueError("unsupported notification priority")
        normalized_recipients = list(
            dict.fromkeys(
                recipient.strip()
                for recipient in self.recipients
                if isinstance(recipient, str) and recipient.strip()
            )
        )
        if self.recipients and not normalized_recipients:
            raise ValueError("notification has no valid recipients")
        object.__setattr__(self, "recipients", normalized_recipients)
        object.__setattr__(self, "metadata", dict(self.metadata))


class NotificationBatchResult(TypedDict):
    """Aggregate notification delivery result."""

    success: int
    failed: int
    errors: list[str]


PolicyTransitionChange = TypedDict(
    "PolicyTransitionChange",
    {"date": str, "from": str, "to": str, "title": str},
)


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

    def send_batch(self, messages: list[NotificationMessage]) -> NotificationBatchResult:
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

    def send_policy_alert(self, level: PolicyLevel, event: PolicyEvent, status: object) -> bool:
        """发送政策档位告警

        Args:
            level: 政策档位
            event: 政策事件
            status: 政策状态对象

        Returns:
            bool: 发送是否成功
        """
        ...

    def send_transition_summary(self, changes: list[dict[str, str]]) -> bool:
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
        self, item: RSSItem, content: str | None = None
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
        self, items: list[tuple[RSSItem, str | None]]
    ) -> list[AIClassificationResult]:
        """
        批量分类

        Args:
            items: (RSS条目, 可选内容) 的列表

        Returns:
            List[AIClassificationResult]: 分类结果列表
        """
        ...
