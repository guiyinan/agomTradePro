"""
Events Domain Module

领域事件总线的 Domain 层。

此模块提供事件驱动架构的基础设施，支持 Beta Gate、Alpha Trigger 和 Decision Rhythm 模块之间的解耦通信。
"""

from .entities import (
    # 事件类型
    EventType,
    # 核心实体
    DomainEvent,
    EventHandler,
    EventSubscription,
    EventFilter,
    EventBusConfig,
    EventMetrics,
    EventSnapshot,
    # 便捷工厂函数
    create_event,
    create_subscription,
    # 类型别名
    EventCallback,
    SubscriptionFilter,
)

from .services import (
    # 事件总线
    EventBus,
    InMemoryEventBus,
    # 全局实例
    get_event_bus,
    reset_event_bus,
    # 装饰器
    event_handler,
)

__all__ = [
    # 事件类型
    "EventType",
    # 核心实体
    "DomainEvent",
    "EventHandler",
    "EventSubscription",
    "EventFilter",
    "EventBusConfig",
    "EventMetrics",
    "EventSnapshot",
    # 便捷工厂函数
    "create_event",
    "create_subscription",
    # 类型别名
    "EventCallback",
    "SubscriptionFilter",
    # 事件总线
    "EventBus",
    "InMemoryEventBus",
    # 全局实例
    "get_event_bus",
    "reset_event_bus",
    # 装饰器
    "event_handler",
]
