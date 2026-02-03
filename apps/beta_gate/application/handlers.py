"""
Beta Gate Event Handlers

处理外部事件，响应 Regime 和 Policy 变化。
"""

import logging
from typing import Optional

from apps.events.domain.entities import DomainEvent, EventHandler, EventType
from ..domain.entities import GateConfigSelector, VisibilityUniverseBuilder
from ..domain.services import get_default_configs


logger = logging.getLogger(__name__)


class BetaGateEventHandler(EventHandler):
    """
    Beta Gate 事件处理器

    响应 Regime 和 Policy 变化事件，自动更新可见性宇宙。

    Attributes:
        universe_builder: 宇宙构建器
        config_selector: 配置选择器
        event_bus: 事件总线（用于发布后续事件）

    Example:
        >>> handler = BetaGateEventHandler(builder, selector, event_bus)
        >>> handler.can_handle(EventType.REGIME_CHANGED)  # True
    """

    def __init__(self, universe_builder=None, config_selector=None, event_bus=None):
        """
        初始化处理器

        Args:
            universe_builder: 宇宙构建器（可选）
            config_selector: 配置选择器（可选）
            event_bus: 事件总线（可选）
        """
        from ..domain.services import VisibilityUniverseBuilder, GateConfigSelector

        self.universe_builder = universe_builder or VisibilityUniverseBuilder()
        self.config_selector = config_selector or GateConfigSelector(get_default_configs())
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """
        判断是否能处理该类型的事件

        Args:
            event_type: 事件类型

        Returns:
            是否能处理
        """
        return event_type in [
            EventType.REGIME_CHANGED,
            EventType.POLICY_LEVEL_CHANGED,
            EventType.REGIME_CONFIDENCE_LOW,
        ]

    def handle(self, event: DomainEvent) -> None:
        """
        处理事件

        Args:
            event: 领域事件
        """
        try:
            if event.event_type == EventType.REGIME_CHANGED:
                self._handle_regime_changed(event)
            elif event.event_type == EventType.POLICY_LEVEL_CHANGED:
                self._handle_policy_changed(event)
            elif event.event_type == EventType.REGIME_CONFIDENCE_LOW:
                self._handle_confidence_low(event)

        except Exception as e:
            logger.error(f"Error in BetaGateEventHandler: {e}", exc_info=True)

    def _handle_regime_changed(self, event: DomainEvent):
        """处理 Regime 变化事件"""
        old_regime = event.get_payload_value("old_regime")
        new_regime = event.get_payload_value("new_regime")
        confidence = event.get_payload_value("confidence", 0.5)

        logger.info(f"Regime changed from {old_regime} to {new_regime}, updating Beta Gate")

        # 更新可见性宇宙
        # 这里可以触发重新评估所有资产
        # 或者标记需要重新评估

        # 发布 Beta Gate 更新事件
        if self.event_bus:
            from apps.events.domain.entities import create_event

            update_event = create_event(
                event_type=EventType.BETA_GATE_EVALUATED,
                payload={
                    "reason": "regime_changed",
                    "old_regime": old_regime,
                    "new_regime": new_regime,
                    "confidence": confidence,
                },
            )
            self.event_bus.publish(update_event)

    def _handle_policy_changed(self, event: DomainEvent):
        """处理 Policy 变化事件"""
        old_level = event.get_payload_value("old_level")
        new_level = event.get_payload_value("new_level")

        logger.info(f"Policy level changed from P{old_level} to P{new_level}, updating Beta Gate")

        # Policy 变化可能影响很多资产的可见性
        # 特别是 P2/P3 档位

        if self.event_bus:
            from apps.events.domain.entities import create_event

            update_event = create_event(
                event_type=EventType.BETA_GATE_EVALUATED,
                payload={
                    "reason": "policy_changed",
                    "old_level": old_level,
                    "new_level": new_level,
                },
            )
            self.event_bus.publish(update_event)

    def _handle_confidence_low(self, event: DomainEvent):
        """处理置信度过低事件"""
        confidence = event.get_payload_value("confidence", 0.0)
        threshold = event.get_payload_value("threshold", 0.3)

        logger.warning(f"Regime confidence {confidence:.2f} below threshold {threshold:.2f}")

        # 低置信度可能需要进入观察模式
        # 或者收紧可见性约束

        if self.event_bus:
            from apps.events.domain.entities import create_event

            update_event = create_event(
                event_type=EventType.BETA_GATE_EVALUATED,
                payload={
                    "reason": "confidence_low",
                    "confidence": confidence,
                    "threshold": threshold,
                    "action": "tighten_constraints",
                },
            )
            self.event_bus.publish(update_event)

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "beta_gate.BetaGateEventHandler"


class GateInvalidationHandler(EventHandler):
    """
    闸门失效处理器

    当 Gate 配置失效时的处理。

    Attributes:
        config_selector: 配置选择器
    """

    def __init__(self, config_selector=None):
        """
        初始化处理器

        Args:
            config_selector: 配置选择器（可选）
        """
        from ..domain.services import GateConfigSelector

        self.config_selector = config_selector or GateConfigSelector(get_default_configs())

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type == EventType.BETA_GATE_BLOCKED

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        asset_code = event.get_payload_value("asset_code")
        reason = event.get_payload_value("blocking_reason")

        logger.info(f"Asset {asset_code} blocked by gate: {reason}")

        # 可以在这里触发额外的逻辑
        # 如通知、记录、调整配置等

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "beta_gate.GateInvalidationHandler"
