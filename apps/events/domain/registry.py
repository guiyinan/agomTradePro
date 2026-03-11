"""
Event Subscriber Registry.

Domain 层注册表， 用于实现订阅注册反转 (IoC)。

重构说明 (2026-03-11):
- 业务模块通过此注册表自行注册订阅器
- events 模块从注册表加载订阅器,不再直接导入业务 handlers
- 支持优先级排序

使用方式:
    # 在业务模块的 apps.py 中
    from apps.events.domain.registry import get_event_subscriber_registry

    registry = get_event_subscriber_registry()
    registry.register(
        module_name="beta_gate",
        event_type=EventType.REGIME_CHANGED,
        handler_factory=lambda: BetaGateEventHandler(...),
        priority=100
    )
"""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol
from datetime import datetime, timezone

from .entities import EventType, EventHandler


logger = logging.getLogger(__name__)


# ============================================================================
# Registry Data Structures
# ============================================================================

@dataclass
class SubscriberInfo:
    """订阅者信息"""
    module_name: str
    event_type: EventType
    handler_factory: Callable[[], EventHandler]
    priority: int = 100
    description: Optional[str] = None

    def __post_init__(self):
        """初始化后验证"""
        if self.handler_factory is None:
            raise ValueError(f"Handler factory cannot be None for {self.module_name}")


@dataclass
class EventSubscriberRegistry:
    """
    事件订阅者注册表

    实现 IoC 模式：业务模块通过此注册表自行注册订阅器,
    events 模块从注册表加载订阅器,不再直接导入业务 handlers.

    Attributes:
        _subscribers: Dict[EventType, List[SubscriberInfo]]
        _sorted: 是否已按优先级排序

    Example:
        >>> # 在 beta_gate/apps.py 中
        >>> from apps.events.domain.registry import get_event_subscriber_registry
        >>> registry = get_event_subscriber_registry()
        >>> registry.register(
        ...     module_name="beta_gate",
        ...     event_type=EventType.REGIME_CHANGED,
        ...     handler_factory=lambda: BetaGateEventHandler(...),
        ...     priority=100
        ... )
    """

    def __init__(self):
        self._subscribers: Dict[EventType, List[SubscriberInfo]] = {}
        self._sorted = False

    def register(
        self,
        module_name: str,
        event_type: EventType,
        handler_factory: Callable[[], EventHandler],
        priority: int = 100,
        description: Optional[str] = None
    ) -> None:
        """
        注册订阅者

        Args:
            module_name: 模块名称
            event_type: 事件类型
            handler_factory: 创建 Handler 的工厂函数
            priority: 优先级 (数字越小优先级越高)
            description: 描述信息

        重构说明 (2026-03-11):
        - 添加重复注册检测，防止同一 (module_name, event_type) 重复注册
        - 如果已存在相同组合，则更新而非追加
        """
        # 检查是否已存在相同的 (module_name, event_type) 组合
        if event_type in self._subscribers:
            for i, existing in enumerate(self._subscribers[event_type]):
                if existing.module_name == module_name:
                    # 已存在，更新而不是追加
                    self._subscribers[event_type][i] = SubscriberInfo(
                        module_name=module_name,
                        event_type=event_type,
                        handler_factory=handler_factory,
                        priority=priority,
                        description=description
                    )
                    self._sorted = False
                    logger.info(
                        f"Updated subscriber: {module_name} -> {event_type.value} (priority={priority})"
                    )
                    return

        # 不存在，创建新订阅者
        subscriber = SubscriberInfo(
            module_name=module_name,
            event_type=event_type,
            handler_factory=handler_factory,
            priority=priority,
            description=description
        )

        if event_type in self._subscribers:
            self._subscribers[event_type].append(subscriber)
        else:
            self._subscribers[event_type] = [subscriber]
        self._sorted = False  # 添加后需要重新排序

        logger.info(
            f"Registered subscriber: {module_name} -> {event_type.value} (priority={priority})"
        )

    def get_subscribers(self, event_type: EventType) -> List[SubscriberInfo]:
        """
        获取指定事件类型的所有订阅者

        Args:
            event_type: 事件类型

        Returns:
            SubscriberInfo 列表 (按优先级排序)
        """
        if not self._sorted:
            # 按优先级排序
            for subscribers in self._subscribers.values():
                subscribers.sort(key=lambda s: s.priority)
            self._sorted = True

        return self._subscribers.get(event_type, [])

    def get_all_subscribers(self) -> List[SubscriberInfo]:
        """
        获取所有订阅者

        Returns:
            所有 SubscriberInfo 列表表
        """
        all_subscribers = []
        for subscribers in self._subscribers.values():
            all_subscribers.extend(subscribers)
        return all_subscribers

    def is_registered(self, module_name: str, event_type: EventType) -> bool:
        """
        检查指定模块是否已注册该事件类型

        Args:
            module_name: 模块名称
            event_type: 事件类型

        Returns:
            是否已注册
        """
        if event_type not in self._subscribers:
            return False
        return any(s.module_name == module_name for s in self._subscribers[event_type])

    def unregister(self, module_name: str, event_type: EventType) -> bool:
        """
        取消注册指定模块的事件订阅

        Args:
            module_name: 模块名称
            event_type: 事件类型

        Returns:
            是否成功取消注册
        """
        if event_type not in self._subscribers:
            return False

        original_count = len(self._subscribers[event_type])
        self._subscribers[event_type] = [
            s for s in self._subscribers[event_type] if s.module_name != module_name
        ]

        if len(self._subscribers[event_type]) < original_count:
            logger.info(f"Unregistered subscriber: {module_name} -> {event_type.value}")
            return True
        return False

    def clear(self) -> None:
        """清空注册表"""
        self._subscribers.clear()
        self._sorted = False


# ============================================================================
# 全局单例
# ============================================================================

_registry_instance: Optional[EventSubscriberRegistry] = None


def get_event_subscriber_registry() -> EventSubscriberRegistry:
    """
    获取事件订阅者注册表单例

    Returns:
        EventSubscriberRegistry 实例
    """
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = EventSubscriberRegistry()
    return _registry_instance


def reset_event_subscriber_registry() -> None:
    """
    重置事件订阅者注册表单例

    用于测试或配置重置。
    """
    global _registry_instance
    _registry_instance = None
