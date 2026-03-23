"""
Event Bus Initializer

事件总线初始化和订阅器注册。
负责在应用启动时设置所有事件订阅。

这是应用层的入口点，协调所有模块的事件处理器。
"""

import logging
from typing import List, Optional

from ..domain.entities import EventType
from ..domain.services import EventBus, EventHandler, InMemoryEventBus
from ..infrastructure.event_store import InMemoryEventStore

logger = logging.getLogger(__name__)


class EventBusInitializer:
    """
    事件总线初始化器

    在应用启动时初始化事件总线并注册所有事件处理器。

    Attributes:
        event_bus: 事件总线实例
        event_store: 事件存储实例（可选）
        handlers: 已注册的处理器列表

    Example:
        >>> initializer = EventBusInitializer()
        >>> initializer.initialize()
        >>> event_bus = initializer.get_event_bus()
    """

    def __init__(self, event_store=None):
        """
        初始化初始化器

        Args:
            event_store: 事件存储（可选，默认使用内存存储）
        """
        self.event_store = event_store or InMemoryEventStore()
        self.event_bus: EventBus | None = None
        self.handlers: list[EventHandler] = []

    def initialize(self) -> EventBus:
        """
        初始化事件总线并注册所有处理器

        流程：
        1. 创建事件总线
        2. 注册 Beta Gate 处理器
        3. 注册 Alpha Trigger 处理器
        4. 注册 Decision Rhythm 处理器
        5. 注册其他处理器
        6. 启动事件总线

        Returns:
            初始化完成的事件总线
        """
        # 创建事件总线（Celery 可用时使用 CeleryEventBus）
        from ..domain.entities import EventBusConfig
        config = EventBusConfig()

        try:
            from ..infrastructure.celery_event_bus import CeleryEventBus, is_celery_available
            if is_celery_available():
                self.event_bus = CeleryEventBus(config)
                logger.info("Using CeleryEventBus for async event publishing")
            else:
                self.event_bus = InMemoryEventBus(config)
                logger.info("Celery not available, using InMemoryEventBus")
        except ImportError:
            self.event_bus = InMemoryEventBus(config)

        # 注册所有处理器
        self._register_all_handlers()

        # 启动事件总线
        self.event_bus.start()

        logger.info(f"Event bus initialized with {len(self.handlers)} handlers")

        return self.event_bus

    def _register_all_handlers(self):
        """
        注册所有事件处理器

        重构说明 (2026-03-11):
        - 从注册表加载业务模块订阅器
        - 移除直接导入业务模块 handlers
        - 保留内部处理器注册
        """
        # 从注册表加载业务模块订阅器
        self._register_from_registry()

        # 注册内部处理器
        self._register_other_handlers()

    def _register_from_registry(self):
        """
        从注册表加载订阅器

        业务模块通过 registry.register() 注册自己的订阅器，
        此方法从注册表读取并创建处理器。
        """
        import uuid

        from ..domain.entities import EventSubscription
        from ..domain.registry import get_event_subscriber_registry

        try:
            registry = get_event_subscriber_registry()
            all_subscribers = registry.get_all_subscribers()

            for subscriber_info in all_subscribers:
                try:
                    # 调用工厂函数创建处理器
                    handler = subscriber_info.handler_factory()

                    # 注入事件总线（如果处理器需要）
                    if hasattr(handler, 'event_bus'):
                        handler.event_bus = self.event_bus

                    # 创建订阅
                    subscription = EventSubscription(
                        subscription_id=f"{subscriber_info.module_name}_{uuid.uuid4().hex[:8]}",
                        event_type=subscriber_info.event_type,
                        handler=handler,
                    )

                    # 注册到事件总线
                    self.event_bus.subscribe(subscription)
                    self.handlers.append(handler)

                    logger.info(
                        f"Registered handler from registry: "
                        f"{subscriber_info.module_name} -> {subscriber_info.event_type.value}"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to create handler for {subscriber_info.module_name}: {e}"
                    )

            logger.info(f"Loaded {len(all_subscribers)} subscribers from registry")

        except Exception as e:
            logger.error(f"Failed to load subscribers from registry: {e}")

    def _register_other_handlers(self):
        """注册其他处理器"""
        # 注册决策执行相关处理器
        self._register_decision_execution_handlers()

        # 添加日志处理器（默认）- 使用 EventSubscription 包装
        import uuid

        from ..domain.entities import EventSubscription, EventType

        log_handler = LoggingEventHandler()
        log_subscription = EventSubscription(
            subscription_id=f"log_handler_{uuid.uuid4().hex[:8]}",
            event_type=EventType.REGIME_CHANGED,  # 使用通用事件类型
            handler=log_handler,
        )
        self.event_bus.subscribe(log_subscription)
        self.handlers.append(log_handler)

    def _register_decision_execution_handlers(self):
        """注册决策执行相关处理器"""
        try:
            import uuid

            from ..domain.entities import EventSubscription, EventType
            from .decision_execution_handlers import (
                DecisionApprovedHandler,
                DecisionExecutedHandler,
                DecisionExecutionFailedHandler,
                DecisionRejectedHandler,
            )

            # 创建处理器
            decision_approved_handler = DecisionApprovedHandler(
                event_bus=self.event_bus
            )
            decision_executed_handler = DecisionExecutedHandler(
                event_bus=self.event_bus
            )
            decision_execution_failed_handler = DecisionExecutionFailedHandler(
                event_bus=self.event_bus
            )
            decision_rejected_handler = DecisionRejectedHandler(
                event_bus=self.event_bus
            )

            # 修复：使用 EventSubscription 包装 handler
            approved_subscription = EventSubscription(
                subscription_id=f"decision_approved_{uuid.uuid4().hex[:8]}",
                event_type=EventType.DECISION_APPROVED,
                handler=decision_approved_handler,
            )
            executed_subscription = EventSubscription(
                subscription_id=f"decision_executed_{uuid.uuid4().hex[:8]}",
                event_type=EventType.DECISION_EXECUTED,
                handler=decision_executed_handler,
            )
            failed_subscription = EventSubscription(
                subscription_id=f"decision_failed_{uuid.uuid4().hex[:8]}",
                event_type=EventType.DECISION_EXECUTION_FAILED,
                handler=decision_execution_failed_handler,
            )
            rejected_subscription = EventSubscription(
                subscription_id=f"decision_rejected_{uuid.uuid4().hex[:8]}",
                event_type=EventType.DECISION_REJECTED,
                handler=decision_rejected_handler,
            )

            # 注册
            self.event_bus.subscribe(approved_subscription)
            self.event_bus.subscribe(executed_subscription)
            self.event_bus.subscribe(failed_subscription)
            self.event_bus.subscribe(rejected_subscription)

            self.handlers.extend([
                decision_approved_handler,
                decision_executed_handler,
                decision_execution_failed_handler,
                decision_rejected_handler,
            ])

            logger.info("Decision execution handlers registered")

        except ImportError as e:
            logger.warning(f"Failed to import decision execution handlers: {e}")

    def get_event_bus(self) -> EventBus | None:
        """
        获取事件总线

        Returns:
            事件总线实例，如果未初始化则返回 None
        """
        return self.event_bus

    def get_handlers(self) -> list[EventHandler]:
        """
        获取已注册的处理器列表

        Returns:
            处理器列表
        """
        return self.handlers.copy()

    def shutdown(self):
        """关闭事件总线"""
        if self.event_bus:
            self.event_bus.stop()
            logger.info("Event bus shut down")


class LoggingEventHandler(EventHandler):
    """
    日志事件处理器

    记录所有事件到日志。

    Attributes:
        level: 日志级别

    Example:
        >>> handler = LoggingEventHandler()
        >>> handler.can_handle(EventType.ANY)  # True
    """

    def __init__(self, level=logging.INFO):
        """
        初始化处理器

        Args:
            level: 日志级别
        """
        self.level = level

    def can_handle(self, event_type: EventType) -> bool:
        """处理所有事件类型"""
        return True

    def handle(self, event) -> None:
        """记录事件"""
        logger.log(
            self.level,
            f"Event: {event.event_type.value} | "
            f"ID: {event.event_id} | "
            f"Payload: {event.payload}"
        )

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "events.LoggingEventHandler"


# 全局单例
_event_bus_initializer: EventBusInitializer | None = None


def get_event_bus_initializer() -> EventBusInitializer:
    """
    获取全局事件总线初始化器

    Returns:
        事件总线初始化器单例
    """
    global _event_bus_initializer

    if _event_bus_initializer is None:
        _event_bus_initializer = EventBusInitializer()

    return _event_bus_initializer


def get_event_bus() -> EventBus | None:
    """
    获取全局事件总线

    Returns:
        事件总线实例，如果未初始化则返回 None
    """
    initializer = get_event_bus_initializer()
    return initializer.get_event_bus()


def initialize_event_bus() -> EventBus:
    """
    初始化事件总线

    Returns:
        初始化完成的事件总线
    """
    initializer = get_event_bus_initializer()
    return initializer.initialize()
