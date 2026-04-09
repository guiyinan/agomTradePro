"""
Events Domain Services

事件总线的核心服务实现。
提供事件发布、订阅、处理的完整功能。

仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timezone
from typing import Any, Dict, List, Optional, Set

from .entities import (
    DomainEvent,
    EventBusConfig,
    EventHandler,
    EventMetrics,
    EventSnapshot,
    EventSubscription,
    EventType,
    create_event,
)

logger = logging.getLogger(__name__)


class EventBus:
    """
    事件总线接口

    定义事件发布和订阅的核心接口。

    Example:
        >>> bus = EventBus()
        >>> bus.subscribe(EventType.REGIME_CHANGED, my_handler)
        >>> bus.publish(create_event(EventType.REGIME_CHANGED, {"regime": "Overheat"}))
    """

    def subscribe(self, subscription: EventSubscription) -> None:
        """
        订阅事件

        Args:
            subscription: 事件订阅
        """
        raise NotImplementedError

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅

        Args:
            subscription_id: 订阅 ID

        Returns:
            是否成功取消
        """
        raise NotImplementedError

    def publish(self, event: DomainEvent) -> None:
        """
        发布事件

        Args:
            event: 领域事件
        """
        raise NotImplementedError

    def publish_async(self, event: DomainEvent) -> None:
        """
        异步发布事件

        Args:
            event: 领域事件
        """
        raise NotImplementedError

    def get_metrics(self) -> EventMetrics:
        """
        获取事件指标

        Returns:
            事件指标
        """
        raise NotImplementedError

    def clear(self) -> None:
        """清空所有订阅和事件"""
        raise NotImplementedError


class InMemoryEventBus(EventBus):
    """
    内存事件总线实现

    线程安全的内存事件总线实现。
    支持同步/异步事件处理、事件重放、指标收集等功能。

    Attributes:
        config: 事件总线配置
        _subscriptions: 事件类型到订阅列表的映射
        _event_queue: 事件队列（用于持久化/重放）
        _lock: 线程锁
        _metrics: 事件指标
        _snapshots: 事件快照（用于调试）

    Example:
        >>> bus = InMemoryEventBus(EventBusConfig())
        >>> subscription = create_subscription(
        ...     EventType.REGIME_CHANGED,
        ...     MyHandler()
        ... )
        >>> bus.subscribe(subscription)
        >>> event = create_event(EventType.REGIME_CHANGED, {"regime": "Overheat"})
        >>> bus.publish(event)
    """

    def __init__(self, config: EventBusConfig = EventBusConfig()):
        """
        初始化事件总线

        Args:
            config: 事件总线配置
        """
        self.config = config
        self._subscriptions: dict[EventType, list[EventSubscription]] = defaultdict(list)
        self._event_queue: deque = deque(maxlen=config.max_queue_size)
        self._snapshots: list[EventSnapshot] = []
        self._lock = threading.RLock()
        self._metrics = EventMetrics()
        self._subscription_ids: set[str] = set()
        self._stopped = False

    def subscribe(self, subscription: EventSubscription) -> None:
        """
        订阅事件

        Args:
            subscription: 事件订阅

        Raises:
            ValueError: 如果订阅 ID 已存在
        """
        with self._lock:
            if subscription.subscription_id in self._subscription_ids:
                raise ValueError(f"Subscription ID {subscription.subscription_id} already exists")

            self._subscriptions[subscription.event_type].append(subscription)
            # 按优先级排序
            self._subscriptions[subscription.event_type].sort(key=lambda s: s.priority)
            self._subscription_ids.add(subscription.subscription_id)
            self._metrics.total_subscribers += 1

            logger.debug(
                f"Subscribed to {subscription.event_type.value}: "
                f"{subscription.subscription_id} (priority={subscription.priority})"
            )

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅

        Args:
            subscription_id: 订阅 ID

        Returns:
            是否成功取消
        """
        with self._lock:
            if subscription_id not in self._subscription_ids:
                return False

            for event_type, subscriptions in self._subscriptions.items():
                for i, sub in enumerate(subscriptions):
                    if sub.subscription_id == subscription_id:
                        subscriptions.pop(i)
                        self._subscription_ids.remove(subscription_id)
                        self._metrics.total_subscribers -= 1
                        logger.debug(f"Unsubscribed: {subscription_id}")
                        return True

            return False

    def unsubscribe_all(self, handler: EventHandler) -> int:
        """
        取消处理器的所有订阅

        Args:
            handler: 事件处理器

        Returns:
            取消的订阅数量
        """
        with self._lock:
            count = 0
            handler_id = handler.get_handler_id()

            for event_type, subscriptions in list(self._subscriptions.items()):
                new_subscriptions = [
                    sub for sub in subscriptions
                    if sub.handler.get_handler_id() != handler_id
                ]
                removed = len(subscriptions) - len(new_subscriptions)

                for sub in subscriptions:
                    if sub.handler.get_handler_id() == handler_id:
                        self._subscription_ids.discard(sub.subscription_id)

                if new_subscriptions:
                    self._subscriptions[event_type] = new_subscriptions
                else:
                    del self._subscriptions[event_type]

                count += removed
                self._metrics.total_subscribers -= removed

            if count > 0:
                logger.debug(f"Unsubscribed {count} subscriptions for handler: {handler_id}")

            return count

    def publish(self, event: DomainEvent) -> None:
        """
        发布事件（同步处理）

        Args:
            event: 领域事件
        """
        if self._stopped:
            logger.warning("Event bus is stopped, ignoring event")
            return

        # 记录事件
        with self._lock:
            self._event_queue.append(event)
            self._metrics.total_published += 1
            self._metrics.last_event_at = event.occurred_at

        # 处理事件
        self._process_event(event)

    def publish_async(self, event: DomainEvent) -> None:
        """
        异步发布事件

        当前实现为简化版，实际应使用线程池或异步框架。

        Args:
            event: 领域事件
        """
        # TODO: 实现真正的异步处理
        self.publish(event)

    def publish_batch(self, events: list[DomainEvent]) -> None:
        """
        批量发布事件

        Args:
            events: 领域事件列表
        """
        for event in events:
            self.publish(event)

    def _process_event(self, event: DomainEvent) -> None:
        """
        处理事件

        Args:
            event: 领域事件
        """
        subscriptions = self._subscriptions.get(event.event_type, [])

        if not subscriptions:
            logger.debug(f"No subscribers for event type: {event.event_type.value}")
            return

        logger.debug(
            f"Processing event {event.event_id} "
            f"({event.event_type.value}) to {len(subscriptions)} subscribers"
        )

        for subscription in subscriptions:
            if not subscription.should_process(event):
                continue

            start_time = datetime.now(UTC)
            success = False
            error_message = None
            retry_count = 0

            try:
                subscription.handler.handle(event)
                success = True
                self._metrics.total_processed += 1

            except Exception as e:
                error_message = str(e)
                self._metrics.total_failed += 1
                logger.error(
                    f"Error handling event {event.event_type.value} "
                    f"by {subscription.subscription_id}: {e}",
                    exc_info=True,
                )

                # 重试逻辑
                if self.config.retry_failed_events and retry_count < self.config.max_retry_attempts:
                    retry_count += 1
                    try:
                        subscription.handler.handle(event)
                        success = True
                        self._metrics.total_failed -= 1
                        self._metrics.total_processed += 1
                        logger.info(f"Retry {retry_count} succeeded for {subscription.subscription_id}")
                    except Exception:
                        pass

            finally:
                # 计算处理时间
                processing_time = (datetime.now(UTC) - start_time).total_seconds() * 1000
                self._update_avg_processing_time(processing_time)

                # 保存快照
                if self.config.enable_persistence:
                    snapshot = EventSnapshot(
                        event=event,
                        processed_at=datetime.now(UTC),
                        handler_id=subscription.handler.get_handler_id(),
                        success=success,
                        error_message=error_message,
                        retry_count=retry_count,
                    )
                    self._snapshots.append(snapshot)

    def _update_avg_processing_time(self, new_time_ms: float) -> None:
        """
        更新平均处理时间

        Args:
            new_time_ms: 新的处理时间（毫秒）
        """
        with self._lock:
            total = self._metrics.total_processed + self._metrics.total_failed
            if total > 0:
                current_avg = self._metrics.avg_processing_time_ms
                self._metrics.avg_processing_time_ms = (
                    (current_avg * (total - 1) + new_time_ms) / total
                )

    def get_metrics(self) -> EventMetrics:
        """
        获取事件指标

        Returns:
            事件指标的深拷贝
        """
        with self._lock:
            return deepcopy(self._metrics)

    def get_snapshots(self, limit: int = 100) -> list[EventSnapshot]:
        """
        获取事件快照

        Args:
            limit: 最大返回数量

        Returns:
            事件快照列表
        """
        with self._lock:
            return list(self._snapshots[-limit:])

    def get_subscription_count(self, event_type: EventType | None = None) -> int:
        """
        获取订阅数量

        Args:
            event_type: 事件类型（可选），None 表示全部

        Returns:
            订阅数量
        """
        with self._lock:
            if event_type is None:
                return len(self._subscription_ids)
            return len(self._subscriptions.get(event_type, []))

    def get_subscriptions(self, event_type: EventType) -> list[EventSubscription]:
        """
        获取指定事件类型的所有订阅

        Args:
            event_type: 事件类型

        Returns:
            订阅列表的深拷贝
        """
        with self._lock:
            return deepcopy(self._subscriptions.get(event_type, []))

    def clear(self) -> None:
        """清空所有订阅和事件"""
        with self._lock:
            self._subscriptions.clear()
            self._event_queue.clear()
            self._snapshots.clear()
            self._subscription_ids.clear()
            self._metrics = EventMetrics()
            logger.info("Event bus cleared")

    def stop(self) -> None:
        """停止事件总线"""
        with self._lock:
            self._stopped = True
            logger.info("Event bus stopped")

    def start(self) -> None:
        """启动事件总线"""
        with self._lock:
            self._stopped = False
            logger.debug("Event bus started")

    def replay_events(self, event_type: EventType | None = None) -> int:
        """
        重放事件

        Args:
            event_type: 事件类型过滤（可选）

        Returns:
            重放的事件数量
        """
        with self._lock:
            events = list(self._event_queue)
            if event_type is not None:
                events = [e for e in events if e.event_type == event_type]

            for event in events:
                self._process_event(event)

            logger.info(f"Replayed {len(events)} events")
            return len(events)


# ========== 全局事件总线实例 ==========

_global_event_bus: InMemoryEventBus | None = None
_global_bus_lock = threading.Lock()


def get_event_bus(config: EventBusConfig | None = None) -> InMemoryEventBus:
    """
    获取全局事件总线实例

    Args:
        config: 事件总线配置（首次创建时使用）

    Returns:
        全局事件总线实例
    """
    global _global_event_bus

    with _global_bus_lock:
        if _global_event_bus is None:
            _global_event_bus = InMemoryEventBus(config or EventBusConfig())
            logger.info("Global event bus initialized")
        return _global_event_bus


def reset_event_bus() -> None:
    """重置全局事件总线（主要用于测试）"""
    global _global_event_bus

    with _global_bus_lock:
        if _global_event_bus is not None:
            _global_event_bus.clear()
            _global_event_bus = None
            logger.info("Global event bus reset")


# ========== 装饰器 ==========


def event_handler(event_type: EventType, filter_criteria: dict[str, Any] | None = None, priority: int = 100):
    """
    事件处理器装饰器

    简化事件处理器注册的装饰器。

    Args:
        event_type: 订阅的事件类型
        filter_criteria: 过滤条件
        priority: 处理优先级

    Example:
        >>> @event_handler(EventType.REGIME_CHANGED)
        ... def handle_regime_change(event: DomainEvent):
        ...     print(f"Regime changed to {event.payload['new_regime']}")
    """
    def decorator(func: Callable[[DomainEvent], None]):
        class FunctionHandler(EventHandler):
            def can_handle(self, et: EventType) -> bool:
                return et == event_type

            def handle(self, event: DomainEvent) -> None:
                func(event)

            def get_handler_id(self) -> str:
                return f"function_handler.{func.__name__}"

        # 自动注册到全局事件总线
        bus = get_event_bus()
        subscription = EventSubscription(
            subscription_id=f"func_{func.__name__}",
            event_type=event_type,
            handler=FunctionHandler(),
            is_active=True,
            filter_criteria=filter_criteria,
            priority=priority,
        )
        bus.subscribe(subscription)

        return func

    return decorator
