"""
Events Application Use Cases

事件用例层，定义事件相关的业务用例。
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Any, Dict, List, Optional, Union

from ..domain.entities import (
    DomainEvent,
    EventHandler,
    # InMemoryEventBus is in services, not entities
    EventMetrics,
    EventSubscription,
    EventType,
    create_event,
    create_subscription,
)
from ..domain.services import InMemoryEventBus, get_event_bus
from .repository_provider import (
    DatabaseEventStore,
    EventReplayHandler,
    SnapshotStore,
    get_event_store,
    get_snapshot_store,
)

logger = logging.getLogger(__name__)


# ========== Request/Response DTOs ==========


@dataclass
class PublishEventRequest:
    """发布事件请求"""

    event_type: EventType
    payload: dict[str, Any]
    metadata: dict[str, Any] | None = None
    event_id: str | None = None
    occurred_at: datetime | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass
class PublishEventResponse:
    """发布事件响应"""

    success: bool
    event_id: str
    published_at: datetime
    subscribers_notified: int = 0
    error_message: str | None = None


@dataclass
class SubscribeToEventRequest:
    """订阅事件请求"""

    event_type: EventType
    handler: EventHandler
    filter_criteria: dict[str, Any] | None = None
    priority: int = 100


@dataclass
class SubscribeToEventResponse:
    """订阅事件响应"""

    success: bool
    subscription_id: str
    subscribed_at: datetime
    error_message: str | None = None


@dataclass
class QueryEventsRequest:
    """查询事件请求"""

    event_type: EventType | None = None
    event_types: list[EventType] | None = None
    correlation_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100


@dataclass
class EventDTO:
    """事件传输对象"""

    event_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    metadata: dict[str, Any]
    correlation_id: str | None = None
    causation_id: str | None = None
    version: int = 1


@dataclass
class QueryEventsResponse:
    """查询事件响应"""

    success: bool
    events: list[EventDTO]
    total_count: int
    queried_at: datetime
    error_message: str | None = None


@dataclass
class ReplayEventsRequest:
    """重放事件请求"""

    event_type: EventType | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 1000
    target_handler: EventHandler | None = None


@dataclass
class ReplayEventsResponse:
    """重放事件响应"""

    success: bool
    events_replayed: int
    replayed_at: datetime
    error_message: str | None = None


@dataclass
class GetEventMetricsResponse:
    """获取事件指标响应"""

    total_published: int
    total_processed: int
    total_failed: int
    total_subscribers: int
    avg_processing_time_ms: float
    last_event_at: datetime | None
    events_by_type: dict[str, int] = field(default_factory=dict)


# ========== Use Cases ==========


class PublishEventUseCase:
    """
    发布事件用例

    负责发布领域事件到事件总线。

    Example:
        >>> use_case = PublishEventUseCase()
        >>> request = PublishEventRequest(
        ...     event_type=EventType.REGIME_CHANGED,
        ...     payload={"regime": "Recovery"}
        ... )
        >>> response = use_case.execute(request)
    """

    def __init__(
        self,
        event_bus: InMemoryEventBus | None = None,
        event_store: DatabaseEventStore | None = None,
    ):
        """
        初始化用例

        Args:
            event_bus: 事件总线（可选，默认使用全局实例）
            event_store: 事件存储（可选，默认使用默认实例）
        """
        self.event_bus = event_bus or get_event_bus()
        self.event_store = event_store or get_event_store()

    def execute(self, request: PublishEventRequest) -> PublishEventResponse:
        """
        执行发布事件

        Args:
            request: 发布事件请求

        Returns:
            发布事件响应
        """
        try:
            # 创建事件
            metadata = request.metadata or {}
            if request.correlation_id:
                metadata["correlation_id"] = request.correlation_id
            if request.causation_id:
                metadata["causation_id"] = request.causation_id

            event = create_event(
                event_type=request.event_type,
                payload=request.payload,
                metadata=metadata,
                event_id=request.event_id,
                occurred_at=request.occurred_at,
            )

            # 持久化事件
            self.event_store.append(event)

            # 发布到事件总线
            self.event_bus.publish(event)

            # 获取订阅者数量
            metrics = self.event_bus.get_metrics()
            subscribers_notified = metrics.total_processed

            return PublishEventResponse(
                success=True,
                event_id=event.event_id,
                published_at=datetime.now(UTC),
                subscribers_notified=subscribers_notified,
            )

        except Exception as e:
            logger.error(f"Failed to publish event: {e}", exc_info=True)
            return PublishEventResponse(
                success=False,
                event_id=request.event_id or "unknown",
                published_at=datetime.now(UTC),
                error_message=str(e),
            )


class SubscribeToEventUseCase:
    """
    订阅事件用例

    负责订阅事件类型到事件总线。

    Example:
        >>> use_case = SubscribeToEventUseCase()
        >>> request = SubscribeToEventRequest(
        ...     event_type=EventType.REGIME_CHANGED,
        ...     handler=my_handler
        ... )
        >>> response = use_case.execute(request)
    """

    def __init__(self, event_bus: InMemoryEventBus | None = None):
        """
        初始化用例

        Args:
            event_bus: 事件总线（可选，默认使用全局实例）
        """
        self.event_bus = event_bus or get_event_bus()

    def execute(self, request: SubscribeToEventRequest) -> SubscribeToEventResponse:
        """
        执行订阅事件

        Args:
            request: 订阅事件请求

        Returns:
            订阅事件响应
        """
        try:
            # 创建订阅
            subscription = create_subscription(
                event_type=request.event_type,
                handler=request.handler,
                filter_criteria=request.filter_criteria,
                priority=request.priority,
            )

            # 注册到事件总线
            self.event_bus.subscribe(subscription)

            return SubscribeToEventResponse(
                success=True,
                subscription_id=subscription.subscription_id,
                subscribed_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Failed to subscribe to event: {e}", exc_info=True)
            return SubscribeToEventResponse(
                success=False,
                subscription_id="",
                subscribed_at=datetime.now(UTC),
                error_message=str(e),
            )


class QueryEventsUseCase:
    """
    查询事件用例

    负责从事件存储查询事件。

    Example:
        >>> use_case = QueryEventsUseCase()
        >>> request = QueryEventsRequest(
        ...     event_type=EventType.REGIME_CHANGED,
        ...     limit=10
        ... )
        >>> response = use_case.execute(request)
    """

    def __init__(self, event_store: DatabaseEventStore | None = None):
        """
        初始化用例

        Args:
            event_store: 事件存储（可选，默认使用默认实例）
        """
        self.event_store = event_store or get_event_store()

    def execute(self, request: QueryEventsRequest) -> QueryEventsResponse:
        """
        执行查询事件

        Args:
            request: 查询事件请求

        Returns:
            查询事件响应
        """
        try:
            # 查询事件
            events = self.event_store.get_events(
                event_type=request.event_type,
                event_types=request.event_types,
                correlation_id=request.correlation_id,
                since=request.since,
                until=request.until,
                limit=request.limit,
            )

            # 转换为 DTO
            event_dtos = [
                EventDTO(
                    event_id=event.event_id,
                    event_type=event.event_type.value,
                    occurred_at=event.occurred_at,
                    payload=event.payload,
                    metadata=event.metadata,
                    correlation_id=event.metadata.get("correlation_id"),
                    causation_id=event.metadata.get("causation_id"),
                    version=event.version,
                )
                for event in events
            ]

            return QueryEventsResponse(
                success=True,
                events=event_dtos,
                total_count=len(event_dtos),
                queried_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Failed to query events: {e}", exc_info=True)
            return QueryEventsResponse(
                success=False,
                events=[],
                total_count=0,
                queried_at=datetime.now(UTC),
                error_message=str(e),
            )


class ReplayEventsUseCase:
    """
    重放事件用例

    负责从事件存储重放事件到处理器。

    Example:
        >>> use_case = ReplayEventsUseCase()
        >>> request = ReplayEventsRequest(
        ...     event_type=EventType.REGIME_CHANGED,
        ...     target_handler=my_handler
        ... )
        >>> response = use_case.execute(request)
    """

    def __init__(
        self,
        event_store: DatabaseEventStore | None = None,
    ):
        """
        初始化用例

        Args:
            event_store: 事件存储（可选，默认使用默认实例）
        """
        self.event_store = event_store or get_event_store()
        self.replay_handler = EventReplayHandler(self.event_store)

    def execute(self, request: ReplayEventsRequest) -> ReplayEventsResponse:
        """
        执行重放事件

        Args:
            request: 重放事件请求

        Returns:
            重放事件响应
        """
        try:
            # 重放事件
            count = self.replay_handler.replay_to(
                subscriber=request.target_handler,
                event_types=[request.event_type] if request.event_type else None,
                since=request.since,
                until=request.until,
                limit=request.limit,
            )

            return ReplayEventsResponse(
                success=True,
                events_replayed=count,
                replayed_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Failed to replay events: {e}", exc_info=True)
            return ReplayEventsResponse(
                success=False,
                events_replayed=0,
                replayed_at=datetime.now(UTC),
                error_message=str(e),
            )


class GetEventMetricsUseCase:
    """
    获取事件指标用例

    负责获取事件总线的运行指标。

    Example:
        >>> use_case = GetEventMetricsUseCase()
        >>> response = use_case.execute()
    """

    def __init__(
        self,
        event_bus: InMemoryEventBus | None = None,
        event_store: DatabaseEventStore | None = None,
    ):
        """
        初始化用例

        Args:
            event_bus: 事件总线（可选，默认使用全局实例）
            event_store: 事件存储（可选，默认使用默认实例）
        """
        self.event_bus = event_bus or get_event_bus()
        self.event_store = event_store or get_event_store()

    def execute(self) -> GetEventMetricsResponse:
        """
        执行获取指标

        Returns:
            事件指标响应
        """
        try:
            # 获取内存事件总线指标
            memory_metrics = self.event_bus.get_metrics()

            # 获取持久化事件指标
            stored_metrics = self.event_store.get_metrics()

            return GetEventMetricsResponse(
                total_published=memory_metrics.total_published,
                total_processed=memory_metrics.total_processed,
                total_failed=memory_metrics.total_failed,
                total_subscribers=memory_metrics.total_subscribers,
                avg_processing_time_ms=memory_metrics.avg_processing_time_ms,
                last_event_at=memory_metrics.last_event_at,
                events_by_type=stored_metrics.events_by_type,
            )

        except Exception as e:
            logger.error(f"Failed to get event metrics: {e}", exc_info=True)
            return GetEventMetricsResponse(
                total_published=0,
                total_processed=0,
                total_failed=0,
                total_subscribers=0,
                avg_processing_time_ms=0.0,
                last_event_at=None,
                events_by_type={},
            )
