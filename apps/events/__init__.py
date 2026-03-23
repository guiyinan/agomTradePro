"""
Events Module

领域事件总线模块。

提供事件驱动架构的基础设施，支持跨模块的松耦合通信。
"""

from .domain import (
    DomainEvent,
    EventBus,
    EventBusConfig,
    EventHandler,
    EventMetrics,
    EventSnapshot,
    EventSubscription,
    EventType,
    InMemoryEventBus,
    create_event,
    create_subscription,
    event_handler,
    reset_event_bus,
)
from .domain import (
    get_event_bus as get_domain_event_bus,
)

# 不在模块级别导入 application 层，避免 Django 初始化时的循环依赖
# 需要使用 application 层时，请显式导入：
# from apps.events.application import EventBusInitializer, initialize_event_bus

__all__ = [
    # Domain 层
    "EventType",
    "DomainEvent",
    "EventHandler",
    "EventSubscription",
    "EventBusConfig",
    "EventMetrics",
    "EventSnapshot",
    "create_event",
    "create_subscription",
    "EventBus",
    "InMemoryEventBus",
    "get_domain_event_bus",
    "reset_event_bus",
    "event_handler",
]
