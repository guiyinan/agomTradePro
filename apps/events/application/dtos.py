"""
Events Application Layer DTOs

事件相关的数据传输对象。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .use_cases import PublishEventRequest


@dataclass
class EventPublishRequestDTO:
    """发布事件请求 DTO"""

    event_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any] | None = None
    event_id: str | None = None
    occurred_at: str | None = None  # ISO 格式时间字符串
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass
class EventSubscriptionRequestDTO:
    """事件订阅请求 DTO"""

    event_type: str
    handler_class: str  # 处理器类路径
    filter_criteria: dict[str, Any] | None = None
    priority: int = 100


@dataclass
class EventQueryRequestDTO:
    """事件查询请求 DTO"""

    event_type: str | None = None
    event_types: list[str] | None = None
    correlation_id: str | None = None
    since: str | None = None  # ISO 格式时间字符串
    until: str | None = None  # ISO 格式时间字符串
    limit: int = 100


@dataclass
class EventReplayRequestDTO:
    """事件重放请求 DTO"""

    event_type: str | None = None
    since: str | None = None  # ISO 格式时间字符串
    until: str | None = None  # ISO 格式时间字符串
    limit: int = 1000
    target_handler_class: str | None = None  # 处理器类路径


# ========== 响应 DTOs ==========


@dataclass
class EventDTO:
    """事件传输对象"""

    event_id: str
    event_type: str
    occurred_at: str  # ISO 格式时间字符串
    payload: dict[str, Any]
    metadata: dict[str, Any]
    correlation_id: str | None = None
    causation_id: str | None = None
    version: int = 1


@dataclass
class BaseResponseDTO:
    """基础响应 DTO"""

    success: bool
    message: str | None = None
    error_code: str | None = None
    timestamp: str = field(default_factory=lambda: timezone.now().isoformat())


@dataclass
class EventPublishResponseDTO(BaseResponseDTO):
    """发布事件响应 DTO"""

    event_id: str = ""
    published_at: str = ""  # ISO 格式时间字符串
    subscribers_notified: int = 0


@dataclass
class EventSubscriptionResponseDTO(BaseResponseDTO):
    """事件订阅响应 DTO"""

    subscription_id: str = ""
    subscribed_at: str = ""  # ISO 格式时间字符串
    event_type: str = ""
    handler_id: str = ""


@dataclass
class EventQueryResponseDTO(BaseResponseDTO):
    """事件查询响应 DTO"""

    events: list[EventDTO] = field(default_factory=list)
    total_count: int = 0
    queried_at: str = ""  # ISO 格式时间字符串
    has_more: bool = False


@dataclass
class EventReplayResponseDTO(BaseResponseDTO):
    """事件重放响应 DTO"""

    events_replayed: int = 0
    replayed_at: str = ""  # ISO 格式时间字符串
    duration_ms: int = 0


@dataclass
class EventMetricsDTO:
    """事件指标 DTO"""

    total_published: int = 0
    total_processed: int = 0
    total_failed: int = 0
    total_subscribers: int = 0
    avg_processing_time_ms: float = 0.0
    last_event_at: str | None = None  # ISO 格式时间字符串
    success_rate: float = 0.0  # 成功率


@dataclass
class EventStatisticsResponseDTO(BaseResponseDTO):
    """事件统计响应 DTO"""

    metrics: EventMetricsDTO = field(default_factory=EventMetricsDTO)
    events_by_type: dict[str, int] = field(default_factory=dict)  # 事件类型到数量的映射
    active_subscriptions: int = 0
    queue_size: int = 0


@dataclass
class EventBusStatusDTO:
    """事件总线状态 DTO"""

    is_running: bool = True
    total_subscribers: int = 0
    queue_size: int = 0
    last_event_at: str | None = None  # ISO 格式时间字符串
    uptime_seconds: float = 0.0


# ========== 便捷转换函数 ==========


def dto_to_event_publish_request(dto: EventPublishRequestDTO) -> "PublishEventRequest":
    """
    转换 DTO 为用例请求

    Args:
        dto: 发布事件请求 DTO

    Returns:
        用例请求
    """
    from datetime import datetime

    from .use_cases import PublishEventRequest

    occurred_at = None
    if dto.occurred_at:
        try:
            occurred_at = datetime.fromisoformat(dto.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    return PublishEventRequest(
        event_type=EventType(dto.event_type),
        payload=dto.payload,
        metadata=dto.metadata,
        event_id=dto.event_id,
        occurred_at=occurred_at,
        correlation_id=dto.correlation_id,
        causation_id=dto.causation_id,
    )


def event_to_dto(event) -> EventDTO:
    """
    转换领域事件为 DTO

    Args:
        event: 领域事件

    Returns:
        事件 DTO
    """
    return EventDTO(
        event_id=event.event_id,
        event_type=event.event_type.value,
        occurred_at=event.occurred_at.isoformat(),
        payload=event.payload,
        metadata=event.metadata,
        correlation_id=event.metadata.get("correlation_id"),
        causation_id=event.metadata.get("causation_id"),
        version=event.version,
    )


def metrics_to_dto(metrics) -> EventMetricsDTO:
    """
    转换事件指标为 DTO

    Args:
        metrics: 事件指标

    Returns:
        指标 DTO
    """
    total = metrics.total_processed + metrics.total_failed
    success_rate = (metrics.total_processed / total * 100) if total > 0 else 0.0

    return EventMetricsDTO(
        total_published=metrics.total_published,
        total_processed=metrics.total_processed,
        total_failed=metrics.total_failed,
        total_subscribers=metrics.total_subscribers,
        avg_processing_time_ms=metrics.avg_processing_time_ms,
        last_event_at=metrics.last_event_at.isoformat() if metrics.last_event_at else None,
        success_rate=success_rate,
    )
