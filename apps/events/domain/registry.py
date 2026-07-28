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
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass

from .entities import EventHandler, EventType

logger = logging.getLogger(__name__)

_MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_MIN_PRIORITY = -10_000
_MAX_PRIORITY = 10_000


# ============================================================================
# Registry Data Structures
# ============================================================================


@dataclass(frozen=True)
class SubscriberInfo:
    """订阅者信息"""

    module_name: str
    event_type: EventType
    handler_factory: Callable[[], EventHandler]
    priority: int = 100
    description: str | None = None

    def __post_init__(self) -> None:
        """初始化后验证"""
        if (
            not isinstance(self.module_name, str)
            or _MODULE_NAME_PATTERN.fullmatch(self.module_name) is None
        ):
            raise ValueError("event_subscriber_module_name_invalid")
        if not isinstance(self.event_type, EventType):
            raise TypeError("event_subscriber_event_type_invalid")
        if not callable(self.handler_factory):
            raise TypeError("event_subscriber_factory_invalid")
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not _MIN_PRIORITY <= self.priority <= _MAX_PRIORITY
        ):
            raise ValueError("event_subscriber_priority_invalid")
        if self.description is not None and (
            not isinstance(self.description, str)
            or len(self.description) > 500
            or any(ord(character) < 32 or ord(character) == 127 for character in self.description)
        ):
            raise ValueError("event_subscriber_description_invalid")


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

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[SubscriberInfo]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        module_name: str,
        event_type: EventType,
        handler_factory: Callable[[], EventHandler],
        priority: int = 100,
        description: str | None = None,
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
        subscriber = SubscriberInfo(
            module_name=module_name,
            event_type=event_type,
            handler_factory=handler_factory,
            priority=priority,
            description=description,
        )
        with self._lock:
            subscribers = self._subscribers.setdefault(event_type, [])
            for index, existing in enumerate(subscribers):
                if existing.module_name == module_name:
                    subscribers[index] = subscriber
                    subscribers.sort(key=lambda item: (item.priority, item.module_name))
                    logger.debug(
                        "Updated subscriber: %s -> %s (priority=%s)",
                        module_name,
                        event_type.value,
                        priority,
                    )
                    return
            subscribers.append(subscriber)
            subscribers.sort(key=lambda item: (item.priority, item.module_name))

        logger.debug(
            "Registered subscriber: %s -> %s (priority=%s)",
            module_name,
            event_type.value,
            priority,
        )

    def get_subscribers(self, event_type: EventType) -> list[SubscriberInfo]:
        """
        获取指定事件类型的所有订阅者

        Args:
            event_type: 事件类型

        Returns:
            SubscriberInfo 列表 (按优先级排序)
        """
        if not isinstance(event_type, EventType):
            raise TypeError("event_subscriber_event_type_invalid")
        with self._lock:
            return list(self._subscribers.get(event_type, ()))

    def get_all_subscribers(self) -> list[SubscriberInfo]:
        """
        获取所有订阅者

        Returns:
            所有 SubscriberInfo 列表表
        """
        with self._lock:
            all_subscribers = [
                subscriber
                for subscribers in self._subscribers.values()
                for subscriber in subscribers
            ]
        return sorted(
            all_subscribers,
            key=lambda item: (item.event_type.value, item.priority, item.module_name),
        )

    def is_registered(self, module_name: str, event_type: EventType) -> bool:
        """
        检查指定模块是否已注册该事件类型

        Args:
            module_name: 模块名称
            event_type: 事件类型

        Returns:
            是否已注册
        """
        if not isinstance(module_name, str) or _MODULE_NAME_PATTERN.fullmatch(module_name) is None:
            return False
        if not isinstance(event_type, EventType):
            return False
        with self._lock:
            return any(
                subscriber.module_name == module_name
                for subscriber in self._subscribers.get(event_type, ())
            )

    def unregister(self, module_name: str, event_type: EventType) -> bool:
        """
        取消注册指定模块的事件订阅

        Args:
            module_name: 模块名称
            event_type: 事件类型

        Returns:
            是否成功取消注册
        """
        if not isinstance(module_name, str) or _MODULE_NAME_PATTERN.fullmatch(module_name) is None:
            return False
        if not isinstance(event_type, EventType):
            return False
        with self._lock:
            subscribers = self._subscribers.get(event_type)
            if not subscribers:
                return False
            remaining = [
                subscriber for subscriber in subscribers if subscriber.module_name != module_name
            ]
            if len(remaining) == len(subscribers):
                return False
            if remaining:
                self._subscribers[event_type] = remaining
            else:
                del self._subscribers[event_type]
        logger.debug(
            "Unregistered subscriber: %s -> %s",
            module_name,
            event_type.value,
        )
        return True

    def clear(self) -> None:
        """清空注册表"""
        with self._lock:
            self._subscribers.clear()


# ============================================================================
# 全局单例
# ============================================================================

_registry_instance: EventSubscriberRegistry | None = None
_registry_lock = threading.RLock()


def get_event_subscriber_registry() -> EventSubscriberRegistry:
    """
    获取事件订阅者注册表单例

    Returns:
        EventSubscriberRegistry 实例
    """
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = EventSubscriberRegistry()
        return _registry_instance


def reset_event_subscriber_registry() -> None:
    """
    重置事件订阅者注册表单例

    用于测试或配置重置。
    """
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
