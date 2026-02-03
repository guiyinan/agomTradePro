"""
Events Domain Entities

领域事件总线的核心实体定义。
仅使用 Python 标准库，不依赖 Django、pandas 等外部库。

This module provides the foundational entities for the event-driven architecture
that integrates Beta Gate, Alpha Trigger, and Decision Rhythm modules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import uuid4


class EventType(Enum):
    """
    事件类型枚举

    定义系统中所有可能的领域事件类型。
    事件是模块间解耦通信的核心机制。
    """

    # ========== Regime 事件 ==========
    REGIME_CHANGED = "regime_changed"
    """Regime 发生变化时触发"""

    REGIME_CONFIDENCE_LOW = "regime_confidence_low"
    """Regime 置信度低于阈值时触发"""

    REGIME_DISTRIBUTION_SHIFT = "regime_distribution_shift"
    """Regime 概率分布发生显著偏移时触发"""

    # ========== Policy 事件 ==========
    POLICY_LEVEL_CHANGED = "policy_level_changed"
    """政策档位发生变化时触发"""

    POLICY_EVENT_CREATED = "policy_event_created"
    """新政策事件被创建时触发"""

    POLICY_EVENT_UPDATED = "policy_event_updated"
    """政策事件被更新时触发"""

    # ========== Signal 事件 ==========
    SIGNAL_CREATED = "signal_created"
    """新投资信号被创建时触发"""

    SIGNAL_APPROVED = "signal_approved"
    """投资信号通过审核时触发"""

    SIGNAL_REJECTED = "signal_rejected"
    """投资信号被拒绝时触发"""

    SIGNAL_TRIGGERED = "signal_triggered"
    """投资信号被触发时触发"""

    SIGNAL_INVALIDATED = "signal_invalidated"
    """投资信号被证伪时触发"""

    SIGNAL_EXPIRED = "signal_expired"
    """投资信号过期时触发"""

    # ========== Trigger 事件 ==========
    ALPHA_TRIGGER_ACTIVATED = "alpha_trigger_activated"
    """Alpha 触发器被激活时触发"""

    ALPHA_TRIGGER_FIRED = "alpha_trigger_fired"
    """Alpha 触发器触发时触发"""

    ALPHA_TRIGGER_INVALIDATED = "alpha_trigger_invalidated"
    """Alpha 触发器被证伪时触发"""

    ALPHA_TRIGGER_EXPIRED = "alpha_trigger_expired"
    """Alpha 触发器过期时触发"""

    # ========== Gate 事件 ==========
    BETA_GATE_EVALUATED = "beta_gate_evaluated"
    """Beta Gate 完成评估时触发"""

    BETA_GATE_PASSED = "beta_gate_passed"
    """资产通过 Beta Gate 时触发"""

    BETA_GATE_BLOCKED = "beta_gate_blocked"
    """资产被 Beta Gate 拦截时触发"""

    # ========== Rhythm 事件 ==========
    DECISION_REQUESTED = "decision_requested"
    """决策请求被提交时触发"""

    DECISION_APPROVED = "decision_approved"
    """决策请求被批准时触发"""

    DECISION_REJECTED = "decision_rejected"
    """决策请求被拒绝时触发"""

    DECISION_EXECUTED = "decision_executed"
    """决策被执行时触发"""

    QUOTA_EXCEEDED = "quota_exceeded"
    """决策配额被用尽时触发"""

    QUOTA_RESET = "quota_reset"
    """决策配额被重置时触发"""

    # ========== Portfolio 事件 ==========
    POSITION_OPENED = "position_opened"
    """持仓被开立时触发"""

    POSITION_CLOSED = "position_closed"
    """持仓被平仓时触发"""

    POSITION_STOPPED = "position_stopped"
    """持仓被止损时触发"""

    POSITION_ADJUSTED = "position_adjusted"
    """持仓被调整时触发"""

    # ========== System 事件 ==========
    SYSTEM_ERROR = "system_error"
    """系统错误时触发"""

    AUDIT_COMPLETED = "audit_completed"
    """审计任务完成时触发"""

    BACKTEST_COMPLETED = "backtest_completed"
    """回测任务完成时触发"""


@dataclass(frozen=True)
class DomainEvent:
    """
    领域事件基类

    所有领域事件的基础数据结构。
    使用 frozen=True 确保事件不可变性。

    Attributes:
        event_id: 事件唯一标识符
        event_type: 事件类型
        occurred_at: 事件发生时间
        payload: 事件负载数据（业务数据）
        metadata: 事件元数据（如 correlation_id、causation_id 等）
        version: 事件版本号（用于模式演进）

    Example:
        >>> event = DomainEvent(
        ...     event_id="evt_123",
        ...     event_type=EventType.REGIME_CHANGED,
        ...     occurred_at=datetime.now(),
        ...     payload={"old_regime": "Recovery", "new_regime": "Overheat"}
        ... )
    """

    event_id: str
    event_type: EventType
    occurred_at: datetime
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def get_payload_value(self, key: str, default: Any = None) -> Any:
        """
        获取 payload 中的值

        Args:
            key: 键名
            default: 默认值

        Returns:
            对应的值，不存在则返回默认值
        """
        return self.payload.get(key, default)

    def get_metadata_value(self, key: str, default: Any = None) -> Any:
        """
        获取 metadata 中的值

        Args:
            key: 键名
            default: 默认值

        Returns:
            对应的值，不存在则返回默认值
        """
        return self.metadata.get(key, default)

    def with_correlation_id(self, correlation_id: str) -> "DomainEvent":
        """
        创建一个带有 correlation_id 的新事件副本

        Args:
            correlation_id: 关联 ID，用于追踪事件链

        Returns:
            新的 DomainEvent 实例
        """
        new_metadata = dict(self.metadata)
        new_metadata["correlation_id"] = correlation_id
        return DomainEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            payload=self.payload,
            metadata=new_metadata,
            version=self.version,
        )

    def with_causation_id(self, causation_id: str) -> "DomainEvent":
        """
        创建一个带有 causation_id 的新事件副本

        Args:
            causation_id: 因果 ID，标识导致此事件的事件

        Returns:
            新的 DomainEvent 实例
        """
        new_metadata = dict(self.metadata)
        new_metadata["causation_id"] = causation_id
        return DomainEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            payload=self.payload,
            metadata=new_metadata,
            version=self.version,
        )


class EventHandler(ABC):
    """
    事件处理器接口

    所有事件处理器必须实现此接口。
    处理器应该是无状态的或有明确的生命周期管理。

    Example:
        >>> class RegimeChangedHandler(EventHandler):
        ...     def can_handle(self, event_type: EventType) -> bool:
        ...         return event_type == EventType.REGIME_CHANGED
        ...
        ...     def handle(self, event: DomainEvent) -> None:
        ...         new_regime = event.get_payload_value("new_regime")
        ...         print(f"Regime changed to {new_regime}")
    """

    @abstractmethod
    def can_handle(self, event_type: EventType) -> bool:
        """
        判断是否能处理该类型的事件

        Args:
            event_type: 事件类型

        Returns:
            如果能处理返回 True，否则返回 False
        """
        pass

    @abstractmethod
    def handle(self, event: DomainEvent) -> None:
        """
        处理事件

        Args:
            event: 要处理的领域事件

        Raises:
            Exception: 处理失败时抛出异常（由事件总线捕获）
        """
        pass

    def get_handler_id(self) -> str:
        """
        获取处理器标识符

        Returns:
            处理器的唯一标识符
        """
        return f"{self.__class__.__module__}.{self.__class__.__name__}"


class EventFilter(Protocol):
    """
    事件过滤器协议

    用于定义复杂的事件过滤逻辑。
    """

    def __call__(self, event: DomainEvent) -> bool:
        """
        判断事件是否应该被处理

        Args:
            event: 待过滤的事件

        Returns:
            True 表示应该处理，False 表示跳过
        """
        ...


@dataclass(frozen=True)
class EventSubscription:
    """
    事件订阅

    表示一个事件处理器对特定类型事件的订阅关系。

    Attributes:
        subscription_id: 订阅唯一标识符
        event_type: 订阅的事件类型
        handler: 事件处理器
        is_active: 是否激活
        filter_criteria: 简单过滤条件（基于 payload 字段）
        event_filter: 复杂过滤函数（可选）
        priority: 处理优先级（数字越小优先级越高）
        subscribe_at: 订阅时间

    Example:
        >>> subscription = EventSubscription(
        ...     subscription_id="sub_123",
        ...     event_type=EventType.REGIME_CHANGED,
        ...     handler=MyHandler(),
        ...     filter_criteria={"source": "official"}
        ... )
    """

    subscription_id: str
    event_type: EventType
    handler: EventHandler
    is_active: bool = True
    filter_criteria: Optional[Dict[str, Any]] = None
    event_filter: Optional[EventFilter] = None
    priority: int = 100
    subscribe_at: datetime = field(default_factory=datetime.now)

    def should_process(self, event: DomainEvent) -> bool:
        """
        判断是否应该处理该事件

        Args:
            event: 待判断的事件

        Returns:
            True 表示应该处理，False 表示跳过
        """
        if not self.is_active:
            return False

        if event.event_type != self.event_type:
            return False

        # 应用简单过滤条件
        if self.filter_criteria:
            for key, value in self.filter_criteria.items():
                if event.payload.get(key) != value:
                    return False

        # 应用复杂过滤函数
        if self.event_filter is not None:
            return self.event_filter(event)

        return True

    def with_priority(self, priority: int) -> "EventSubscription":
        """
        创建一个带有新优先级的订阅副本

        Args:
            priority: 新的优先级

        Returns:
            新的 EventSubscription 实例
        """
        return EventSubscription(
            subscription_id=self.subscription_id,
            event_type=self.event_type,
            handler=self.handler,
            is_active=self.is_active,
            filter_criteria=self.filter_criteria,
            event_filter=self.event_filter,
            priority=priority,
            subscribe_at=self.subscribe_at,
        )


@dataclass(frozen=True)
class EventBusConfig:
    """
    事件总线配置

    定义事件总线的运行参数。

    Attributes:
        max_queue_size: 事件队列最大长度
        enable_persistence: 是否启用事件持久化
        async_processing: 是否异步处理事件
        retry_failed_events: 是否重试失败的事件
        max_retry_attempts: 最大重试次数
        event_ttl: 事件生存时间（秒）
        enable_metrics: 是否启用指标收集
    """

    max_queue_size: int = 10000
    enable_persistence: bool = True
    async_processing: bool = False
    retry_failed_events: bool = True
    max_retry_attempts: int = 3
    event_ttl: int = 86400  # 24 hours
    enable_metrics: bool = True


@dataclass(frozen=True)
class EventMetrics:
    """
    事件指标

    用于收集和报告事件总线的运行指标。

    Attributes:
        total_published: 发布事件总数
        total_processed: 处理事件总数
        total_failed: 失败事件总数
        total_subscribers: 订阅者总数
        avg_processing_time_ms: 平均处理时间（毫秒）
        last_event_at: 最后一个事件的时间
    """

    total_published: int = 0
    total_processed: int = 0
    total_failed: int = 0
    total_subscribers: int = 0
    avg_processing_time_ms: float = 0.0
    last_event_at: Optional[datetime] = None


@dataclass(frozen=True)
class EventSnapshot:
    """
    事件快照

    用于事件重放和调试的事件记录。

    Attributes:
        event: 原始事件
        processed_at: 处理时间
        handler_id: 处理器 ID
        success: 是否成功处理
        error_message: 错误信息（如果失败）
        retry_count: 重试次数
    """

    event: DomainEvent
    processed_at: datetime
    handler_id: str
    success: bool
    error_message: Optional[str] = None
    retry_count: int = 0


# ========== 便捷工厂函数 ==========


def create_event(
    event_type: EventType,
    payload: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> DomainEvent:
    """
    创建领域事件的便捷函数

    Args:
        event_type: 事件类型
        payload: 事件负载
        metadata: 事件元数据
        event_id: 事件 ID（可选，默认自动生成）
        occurred_at: 发生时间（可选，默认当前时间）

    Returns:
        DomainEvent 实例

    Example:
        >>> event = create_event(
        ...     event_type=EventType.REGIME_CHANGED,
        ...     payload={"new_regime": "Overheat"}
        ... )
    """
    return DomainEvent(
        event_id=event_id or str(uuid4()),
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(),
        payload=payload,
        metadata=metadata or {},
    )


def create_subscription(
    event_type: EventType,
    handler: EventHandler,
    filter_criteria: Optional[Dict[str, Any]] = None,
    priority: int = 100,
) -> EventSubscription:
    """
    创建事件订阅的便捷函数

    Args:
        event_type: 事件类型
        handler: 事件处理器
        filter_criteria: 过滤条件
        priority: 优先级

    Returns:
        EventSubscription 实例
    """
    return EventSubscription(
        subscription_id=str(uuid4()),
        event_type=event_type,
        handler=handler,
        is_active=True,
        filter_criteria=filter_criteria,
        priority=priority,
    )


# ========== 类型别名 ==========

EventCallback = Callable[[DomainEvent], None]
"""事件回调函数类型别名"""

SubscriptionFilter = Callable[[EventSubscription], bool]
"""订阅过滤器类型别名"""
