"""
Events Domain Rules

事件领域规则定义。
仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from .entities import (
    DomainEvent,
    EventBusConfig,
    EventSnapshot,
    EventSubscription,
    EventType,
)


class Rule(ABC):
    """规则基类"""

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估规则

        Args:
            context: 上下文数据

        Returns:
            是否通过规则
        """
        pass


@dataclass(frozen=True)
class EventPriorityRule(Rule):
    """
    事件优先级规则

    根据事件类型和内容确定事件处理优先级。

    Attributes:
        priority_mapping: 事件类型到优先级的映射
    """

    priority_mapping: dict[EventType, int] = field(default_factory=dict)

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件优先级

        Args:
            context: 上下文，包含 event

        Returns:
            是否为高优先级（优先级 < 50）
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        priority = self.priority_mapping.get(event.event_type, 100)
        return priority < 50

    def get_priority(self, event: DomainEvent) -> int:
        """
        获取事件优先级

        Args:
            event: 领域事件

        Returns:
            优先级（数字越小优先级越高）
        """
        return self.priority_mapping.get(event.event_type, 100)


@dataclass(frozen=True)
class EventFilterRule(Rule):
    """
    事件过滤规则

    根据条件过滤事件。

    Attributes:
        allowed_types: 允许的事件类型
        blocked_types: 阻止的事件类型
        require_metadata: 必需的元数据字段
    """

    allowed_types: set[EventType] | None = None
    blocked_types: set[EventType] | None = None
    require_metadata: set[str] | None = None

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件是否应该被处理

        Args:
            context: 上下文，包含 event

        Returns:
            是否应该处理
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        # 检查阻止列表
        if self.blocked_types and event.event_type in self.blocked_types:
            return False

        # 检查允许列表
        if self.allowed_types and event.event_type not in self.allowed_types:
            return False

        # 检查必需元数据
        if self.require_metadata:
            for key in self.require_metadata:
                if key not in event.metadata:
                    return False

        return True


@dataclass(frozen=True)
class EventDeduplicationRule(Rule):
    """
    事件去重规则

    防止重复事件被处理。

    Attributes:
        dedup_window: 去重时间窗口（秒）
    """

    dedup_window: int = 60  # 默认60秒窗口
    _seen_events: dict[str, datetime] = field(default_factory=dict)

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件是否重复

        Args:
            context: 上下文，包含 event

        Returns:
            是否为重复事件（True 表示重复，应该被过滤）
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        # 创建事件签名
        signature = self._create_signature(event)

        # 检查是否在时间窗口内
        if signature in self._seen_events:
            last_seen = self._seen_events[signature]
            if (datetime.now(UTC) - last_seen).total_seconds() < self.dedup_window:
                return True  # 重复事件

        # 更新最后见时间
        self._seen_events[signature] = datetime.now(UTC)
        return False

    def _create_signature(self, event: DomainEvent) -> str:
        """
        创建事件签名

        Args:
            event: 领域事件

        Returns:
            事件签名
        """
        # 使用事件类型和主要 payload 字段创建签名
        import hashlib
        import json

        key_parts = [event.event_type.value]

        # 添加关键 payload 字段
        if "regime" in event.payload:
            key_parts.append(f"regime={event.payload['regime']}")
        if "asset_code" in event.payload:
            key_parts.append(f"asset={event.payload['asset_code']}")
        if "signal_id" in event.payload:
            key_parts.append(f"signal={event.payload['signal_id']}")

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def cleanup_old_events(self, older_than: int = 3600) -> int:
        """
        清理旧的事件记录

        Args:
            older_than: 清理超过此时间（秒）的记录

        Returns:
            清理的数量
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than)
        to_remove = [
            sig for sig, ts in self._seen_events.items()
            if ts < cutoff
        ]

        for sig in to_remove:
            del self._seen_events[sig]

        return len(to_remove)


@dataclass(frozen=True)
class EventThrottleRule(Rule):
    """
    事件节流规则

    限制事件的处理频率。

    Attributes:
        max_events_per_window: 时间窗口内最大事件数
        window_seconds: 时间窗口（秒）
    """

    max_events_per_window: int = 100
    window_seconds: int = 60
    _event_counts: dict[str, list[datetime]] = field(default_factory=dict)

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件是否应该被节流

        Args:
            context: 上下文，包含 event

        Returns:
            是否应该被节流（True 表示应该节流）
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        event_type = event.event_type.value
        now = datetime.now(UTC)

        # 获取该类型事件的时间戳列表
        timestamps = self._event_counts.setdefault(event_type, [])

        # 清理窗口外的时间戳
        cutoff = now - timedelta(seconds=self.window_seconds)
        self._event_counts[event_type] = [ts for ts in timestamps if ts > cutoff]
        timestamps = self._event_counts[event_type]

        # 检查是否超过限制
        if len(timestamps) >= self.max_events_per_window:
            return True  # 应该节流

        # 添加当前事件
        timestamps.append(now)
        return False


@dataclass(frozen=True)
class EventAgeRule(Rule):
    """
    事件时效性规则

    检查事件是否过期。

    Attributes:
        max_age_seconds: 最大事件年龄（秒）
    """

    max_age_seconds: int = 3600  # 默认1小时

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件是否过期

        Args:
            context: 上下文，包含 event

        Returns:
            是否过期（True 表示过期，应该被过滤）
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        age = (datetime.now(UTC) - event.occurred_at).total_seconds()
        return age > self.max_age_seconds


@dataclass(frozen=True)
class EventValidationRule(Rule):
    """
    事件验证规则

    验证事件的完整性和有效性。

    Attributes:
        require_correlation_id: 是否需要关联 ID
        require_causation_id: 是否需要因果 ID
        min_payload_size: 最小 payload 大小
        max_payload_size: 最大 payload 大小
    """

    require_correlation_id: bool = False
    require_causation_id: bool = False
    min_payload_size: int = 0
    max_payload_size: int = 10000

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估事件是否有效

        Args:
            context: 上下文，包含 event

        Returns:
            是否有效（True 表示有效）
        """
        event = context.get("event")
        if not event or not isinstance(event, DomainEvent):
            return False

        # 检查必需字段
        if self.require_correlation_id and not event.metadata.get("correlation_id"):
            return False

        if self.require_causation_id and not event.metadata.get("causation_id"):
            return False

        # 检查 payload 大小
        payload_size = len(str(event.payload))
        if payload_size < self.min_payload_size or payload_size > self.max_payload_size:
            return False

        return True


class EventRuleEngine:
    """
    事件规则引擎

    组合多个规则对事件进行综合评估。

    Example:
        >>> engine = EventRuleEngine()
        >>> engine.add_rule(EventFilterRule(...))
        >>> engine.add_rule(EventDeduplicationRule(...))
        >>> result = engine.evaluate(event)
    """

    def __init__(self):
        """初始化规则引擎"""
        self._rules: list[Rule] = []
        self._rule_names: dict[Rule, str] = {}

    def add_rule(self, rule: Rule, name: str | None = None) -> None:
        """
        添加规则

        Args:
            rule: 规则
            name: 规则名称
        """
        self._rules.append(rule)
        self._rule_names[rule] = name or rule.__class__.__name__

    def remove_rule(self, rule: Rule) -> None:
        """
        移除规则

        Args:
            rule: 规则
        """
        if rule in self._rules:
            self._rules.remove(rule)
            self._rule_names.pop(rule, None)

    def should_process(self, event: DomainEvent) -> tuple[bool, list[str]]:
        """
        判断事件是否应该被处理

        Args:
            event: 领域事件

        Returns:
            (是否应该处理, 拒绝原因列表)
        """
        context = {"event": event}
        rejection_reasons = []

        for rule in self._rules:
            try:
                result = rule.evaluate(context)

                # 根据规则类型判断结果的含义
                if isinstance(rule, EventFilterRule):
                    if not result:
                        rejection_reasons.append(f"过滤规则: {self._rule_names[rule]}")

                elif isinstance(rule, EventDeduplicationRule):
                    if result:
                        rejection_reasons.append(f"重复事件: {self._rule_names[rule]}")

                elif isinstance(rule, EventThrottleRule):
                    if result:
                        rejection_reasons.append(f"事件节流: {self._rule_names[rule]}")

                elif isinstance(rule, EventAgeRule):
                    if result:
                        rejection_reasons.append(f"事件过期: {self._rule_names[rule]}")

                elif isinstance(rule, EventValidationRule):
                    if not result:
                        rejection_reasons.append(f"事件无效: {self._rule_names[rule]}")

            except Exception as e:
                rejection_reasons.append(f"规则执行错误: {self._rule_names[rule]} - {str(e)}")

        should_process = len(rejection_reasons) == 0
        return should_process, rejection_reasons

    def get_rule_count(self) -> int:
        """
        获取规则数量

        Returns:
            规则数量
        """
        return len(self._rules)

    def clear(self) -> None:
        """清空所有规则"""
        self._rules.clear()
        self._rule_names.clear()


# ========== 预定义规则集 ==========


def create_default_rule_engine() -> EventRuleEngine:
    """
    创建默认的规则引擎

    Returns:
        配置好的规则引擎
    """
    engine = EventRuleEngine()

    # 添加事件时效性规则（1小时）
    engine.add_rule(EventAgeRule(max_age_seconds=3600), "时效性检查")

    # 添加事件验证规则
    engine.add_rule(EventValidationRule(
        require_correlation_id=False,
        require_causation_id=False,
    ), "有效性验证")

    # 添加事件去重规则（60秒窗口）
    engine.add_rule(EventDeduplicationRule(dedup_window=60), "去重检查")

    # 添加事件节流规则（每分钟最多100个同类型事件）
    engine.add_rule(EventThrottleRule(
        max_events_per_window=100,
        window_seconds=60
    ), "频率限制")

    return engine


def create_strict_rule_engine() -> EventRuleEngine:
    """
    创建严格的规则引擎

    Returns:
            配置好的严格规则引擎
    """
    engine = EventRuleEngine()

    # 添加事件时效性规则（30分钟）
    engine.add_rule(EventAgeRule(max_age_seconds=1800), "严格时效性检查")

    # 添加事件验证规则（需要关联ID）
    engine.add_rule(EventValidationRule(
        require_correlation_id=True,
        require_causation_id=False,
    ), "严格有效性验证")

    # 添加事件去重规则（300秒窗口）
    engine.add_rule(EventDeduplicationRule(dedup_window=300), "严格去重检查")

    # 添加事件节流规则（每分钟最多50个同类型事件）
    engine.add_rule(EventThrottleRule(
        max_events_per_window=50,
        window_seconds=60
    ), "严格频率限制")

    return engine
