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
        self.event_bus: Optional[EventBus] = None
        self.handlers: List[EventHandler] = []

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
        # 创建事件总线
        from ..domain.entities import EventBusConfig
        config = EventBusConfig()
        self.event_bus = InMemoryEventBus(config)

        # 注册所有处理器
        self._register_all_handlers()

        # 启动事件总线
        self.event_bus.start()

        logger.info(f"Event bus initialized with {len(self.handlers)} handlers")

        return self.event_bus

    def _register_all_handlers(self):
        """注册所有事件处理器"""
        # 注册 Beta Gate 处理器
        self._register_beta_gate_handlers()

        # 注册 Alpha Trigger 处理器
        self._register_alpha_trigger_handlers()

        # 注册 Decision Rhythm 处理器
        self._register_decision_rhythm_handlers()

        # 注册其他处理器
        self._register_other_handlers()

    def _register_beta_gate_handlers(self):
        """注册 Beta Gate 处理器"""
        try:
            from apps.beta_gate.application.handlers import (
                BetaGateEventHandler,
                GateInvalidationHandler,
            )
            from apps.beta_gate.domain.services import (
                VisibilityUniverseBuilder,
                GateConfigSelector,
            )
            from apps.beta_gate.domain.entities import get_default_configs

            # 创建处理器
            beta_gate_handler = BetaGateEventHandler(
                universe_builder=VisibilityUniverseBuilder(),
                config_selector=GateConfigSelector(get_default_configs()),
                event_bus=self.event_bus,
            )
            gate_invalidation_handler = GateInvalidationHandler(
                config_selector=GateConfigSelector(get_default_configs()),
            )

            # 修复：使用 EventSubscription 包装 handler
            from ..domain.entities import EventSubscription, EventType
            import uuid

            beta_subscription = EventSubscription(
                subscription_id=f"beta_gate_{uuid.uuid4().hex[:8]}",
                event_type=EventType.REGIME_CHANGED,
                handler=beta_gate_handler,
            )
            gate_subscription = EventSubscription(
                subscription_id=f"gate_invalid_{uuid.uuid4().hex[:8]}",
                event_type=EventType.POLICY_LEVEL_CHANGED,
                handler=gate_invalidation_handler,
            )

            # 注册
            self.event_bus.subscribe(beta_subscription)
            self.event_bus.subscribe(gate_subscription)

            self.handlers.extend([beta_gate_handler, gate_invalidation_handler])

            logger.info("Beta Gate handlers registered")

        except ImportError as e:
            logger.warning(f"Failed to import Beta Gate handlers: {e}")

    def _register_alpha_trigger_handlers(self):
        """注册 Alpha Trigger 处理器"""
        try:
            from apps.alpha_trigger.application.handlers import (
                AlphaTriggerEventHandler,
                TriggerInvalidationHandler,
                CandidatePromotionHandler,
            )

            # Alpha Trigger 需要仓储，这里先注册空实现
            # 实际使用时需要注入依赖
            alpha_trigger_handler = AlphaTriggerEventHandler(
                create_trigger_use_case=None,  # 需要注入
                event_bus=self.event_bus,
            )

            # 修复：使用 EventSubscription 包装 handler
            from ..domain.entities import EventSubscription, EventType
            import uuid

            subscription = EventSubscription(
                subscription_id=f"alpha_trigger_{uuid.uuid4().hex[:8]}",
                event_type=EventType.ALPHA_TRIGGER_ACTIVATED,
                handler=alpha_trigger_handler,
            )

            # 注册
            self.event_bus.subscribe(subscription)

            self.handlers.append(alpha_trigger_handler)

            logger.info("Alpha Trigger handlers registered")

        except ImportError as e:
            logger.warning(f"Failed to import Alpha Trigger handlers: {e}")

    def _register_decision_rhythm_handlers(self):
        """注册 Decision Rhythm 处理器"""
        try:
            from apps.decision_rhythm.application.handlers import (
                DecisionRhythmEventHandler,
                QuotaMonitorHandler,
                CooldownEventHandler,
            )
            from apps.decision_rhythm.domain.services import (
                QuotaManager,
                CooldownManager,
            )

            # 创建处理器
            rhythm_handler = DecisionRhythmEventHandler(
                quota_manager=QuotaManager(),
                cooldown_manager=CooldownManager(),
                event_bus=self.event_bus,
            )

            # 修复：使用 EventSubscription 包装 handler
            from ..domain.entities import EventSubscription, EventType
            import uuid

            subscription = EventSubscription(
                subscription_id=f"decision_rhythm_{uuid.uuid4().hex[:8]}",
                event_type=EventType.DECISION_APPROVED,
                handler=rhythm_handler,
            )

            # 注册
            self.event_bus.subscribe(subscription)

            self.handlers.append(rhythm_handler)

            logger.info("Decision Rhythm handlers registered")

        except ImportError as e:
            logger.warning(f"Failed to import Decision Rhythm handlers: {e}")

    def _register_other_handlers(self):
        """注册其他处理器"""
        # 注册决策执行相关处理器
        self._register_decision_execution_handlers()

        # 添加日志处理器（默认）- 使用 EventSubscription 包装
        from ..domain.entities import EventSubscription, EventType
        import uuid

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
            from .decision_execution_handlers import (
                DecisionApprovedHandler,
                DecisionExecutedHandler,
                DecisionExecutionFailedHandler,
            )
            from ..domain.entities import EventSubscription, EventType
            import uuid

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

            # 注册
            self.event_bus.subscribe(approved_subscription)
            self.event_bus.subscribe(executed_subscription)
            self.event_bus.subscribe(failed_subscription)

            self.handlers.extend([
                decision_approved_handler,
                decision_executed_handler,
                decision_execution_failed_handler,
            ])

            logger.info("Decision execution handlers registered")

        except ImportError as e:
            logger.warning(f"Failed to import decision execution handlers: {e}")

    def get_event_bus(self) -> Optional[EventBus]:
        """
        获取事件总线

        Returns:
            事件总线实例，如果未初始化则返回 None
        """
        return self.event_bus

    def get_handlers(self) -> List[EventHandler]:
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
_event_bus_initializer: Optional[EventBusInitializer] = None


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


def get_event_bus() -> Optional[EventBus]:
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
