"""
Decision Rhythm Event Handlers

处理决策批准/拒绝事件，响应配额变化。
"""

import logging
from typing import Any, Protocol

from apps.events.domain.entities import DomainEvent, EventHandler, EventType, create_event

from ..domain.entities import CooldownPeriod, QuotaPeriod
from ..domain.services import CooldownManager, QuotaManager

logger = logging.getLogger(__name__)


class EventPublisherProtocol(Protocol):
    """Minimal event publisher required by rhythm handlers."""

    def publish(self, event: DomainEvent) -> None: ...


class QuotaManagerProtocol(Protocol):
    """Quota status surface required by event handlers."""

    def get_quota_status(self, period: QuotaPeriod) -> dict[str, Any]: ...


class CooldownManagerProtocol(Protocol):
    """Cooldown lookup surface required by event handlers."""

    def get_cooldown(self, asset_code: str) -> CooldownPeriod: ...


class DecisionRhythmEventHandler(EventHandler):
    """
    决策节奏事件处理器

    响应决策批准/拒绝事件，维护配额和冷却期状态。

    Attributes:
        quota_manager: 配额管理器
        cooldown_manager: 冷却管理器
        event_bus: 事件总线（用于发布后续事件）

    Example:
        >>> handler = DecisionRhythmEventHandler(quota_mgr, cooldown_mgr, event_bus)
        >>> handler.can_handle(EventType.DECISION_APPROVED)  # True
    """

    def __init__(
        self,
        quota_manager: QuotaManagerProtocol | None = None,
        cooldown_manager: CooldownManagerProtocol | None = None,
        event_bus: EventPublisherProtocol | None = None,
    ) -> None:
        """
        初始化处理器

        Args:
            quota_manager: 配额管理器（可选）
            cooldown_manager: 冷却管理器（可选）
            event_bus: 事件总线（可选）
        """
        self.quota_manager = quota_manager or QuotaManager()
        self.cooldown_manager = cooldown_manager or CooldownManager()
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type in [
            EventType.DECISION_APPROVED,
            EventType.DECISION_REJECTED,
            EventType.ALPHA_TRIGGER_FIRED,
            EventType.QUOTA_WARNING,
        ]

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        try:
            if event.event_type == EventType.DECISION_APPROVED:
                self._handle_decision_approved(event)
            elif event.event_type == EventType.DECISION_REJECTED:
                self._handle_decision_rejected(event)
            elif event.event_type == EventType.ALPHA_TRIGGER_FIRED:
                self._handle_trigger_fired(event)
            elif event.event_type == EventType.QUOTA_WARNING:
                self._handle_quota_warning(event)

        except Exception as e:
            logger.error(f"Error in DecisionRhythmEventHandler: {e}", exc_info=True)

    def _handle_decision_approved(self, event: DomainEvent) -> None:
        """处理决策批准事件"""
        asset_code = event.get_payload_value("asset_code")
        direction = event.get_payload_value("direction")
        priority = event.get_payload_value("priority")

        logger.info(f"Decision approved: {asset_code} {direction} ({priority})")

        # 配额已经在提交时消耗，这里主要是记录
        # 冷却期已经在提交时设置

    def _handle_decision_rejected(self, event: DomainEvent) -> None:
        """处理决策拒绝事件"""
        asset_code = event.get_payload_value("asset_code")
        reason = event.get_payload_value("rejection_reason")

        logger.info(f"Decision rejected: {asset_code} - {reason}")

        # 拒绝的决策不消耗配额，但可能需要记录原因

    def _handle_trigger_fired(self, event: DomainEvent) -> None:
        """处理触发器触发事件"""
        trigger_id = event.get_payload_value("trigger_id")
        asset_code = event.get_payload_value("asset_code")
        strength = event.get_payload_value("strength")

        logger.info(f"Trigger fired: {trigger_id} for {asset_code} (strength: {strength})")

        # 触发器触发后，可以创建决策请求
        # 这里可能需要调用 SubmitDecisionRequestUseCase

    def _handle_quota_warning(self, event: DomainEvent) -> None:
        """处理配额警告事件"""
        period = event.get_payload_value("period")
        remaining = event.get_payload_value("remaining")
        total = event.get_payload_value("total")

        logger.warning(f"Quota warning: {period} - {remaining}/{total} remaining")

        # 配额不足时，可能需要：
        # 1. 通知用户
        # 2. 自动拒绝低优先级请求
        # 3. 考虑配额扩展

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "decision_rhythm.DecisionRhythmEventHandler"


class QuotaMonitorHandler(EventHandler):
    """
    配额监控处理器

    监控配额使用情况，发布警告事件。

    Attributes:
        quota_manager: 配额管理器
        event_bus: 事件总线

    Example:
        >>> handler = QuotaMonitorHandler(quota_mgr, event_bus)
    """

    WARNING_THRESHOLD = 0.2  # 剩余 20% 时警告

    def __init__(
        self,
        quota_manager: QuotaManagerProtocol,
        event_bus: EventPublisherProtocol | None,
    ) -> None:
        """
        初始化处理器

        Args:
            quota_manager: 配额管理器
            event_bus: 事件总线
        """
        self.quota_manager = quota_manager
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        # 可以定时触发，或者响应决策事件
        return event_type in [
            EventType.DECISION_APPROVED,
        ]

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        if event.event_type == EventType.DECISION_APPROVED:
            # 检查配额是否接近上限
            self._check_quotas()

    def _check_quotas(self) -> None:
        """检查所有配额"""
        for period in QuotaPeriod:
            status = self.quota_manager.get_quota_status(period)
            remaining_value = status.get("remaining_decisions", 0)
            total_value = status.get("max_decisions", 0)
            remaining = (
                int(remaining_value)
                if isinstance(remaining_value, (int, float))
                and not isinstance(remaining_value, bool)
                else 0
            )
            total = (
                int(total_value)
                if isinstance(total_value, (int, float)) and not isinstance(total_value, bool)
                else 0
            )

            if total > 0 and remaining / total < self.WARNING_THRESHOLD:
                # 发布警告事件
                warning_event = create_event(
                    event_type=EventType.QUOTA_WARNING,
                    payload={
                        "period": period.value,
                        "remaining": remaining,
                        "total": total,
                        "usage_rate": (total - remaining) / total,
                    },
                )
                if self.event_bus is not None:
                    self.event_bus.publish(warning_event)

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "decision_rhythm.QuotaMonitorHandler"


class CooldownEventHandler(EventHandler):
    """
    冷却期事件处理器

    管理资产的冷却期状态。

    Attributes:
        cooldown_manager: 冷却管理器
        event_bus: 事件总线

    Example:
        >>> handler = CooldownEventHandler(cooldown_mgr, event_bus)
    """

    def __init__(
        self,
        cooldown_manager: CooldownManagerProtocol,
        event_bus: EventPublisherProtocol | None,
    ) -> None:
        """
        初始化处理器

        Args:
            cooldown_manager: 冷却管理器
            event_bus: 事件总线
        """
        self.cooldown_manager = cooldown_manager
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type in [
            EventType.DECISION_APPROVED,
            EventType.SIGNAL_TRIGGERED,
        ]

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        try:
            if event.event_type == EventType.DECISION_APPROVED:
                self._handle_decision_approved(event)
            elif event.event_type == EventType.SIGNAL_TRIGGERED:
                self._handle_signal_triggered(event)

        except Exception as e:
            logger.error(f"Error in CooldownEventHandler: {e}", exc_info=True)

    def _handle_decision_approved(self, event: DomainEvent) -> None:
        """处理决策批准事件"""
        asset_code = event.get_payload_value("asset_code")
        direction = event.get_payload_value("direction")

        # 记录冷却期已经在提交时设置
        logger.info(f"Cooldown period started for {asset_code} after {direction}")

    def _handle_signal_triggered(self, event: DomainEvent) -> None:
        """处理信号触发事件"""
        asset_code = event.get_payload_value("asset_code")
        if not isinstance(asset_code, str) or not asset_code.strip():
            logger.warning("Ignored signal event without a valid asset code")
            return

        # 检查冷却期
        cooldown_remaining = self.cooldown_manager.get_cooldown(
            asset_code,
        ).decision_ready_in_hours

        if cooldown_remaining > 0:
            logger.info(
                f"Asset {asset_code} is in cooldown: {cooldown_remaining:.1f} hours remaining"
            )

            # 发布冷却中事件
            cooldown_event = create_event(
                event_type=EventType.DECISION_REJECTED,
                payload={
                    "asset_code": asset_code,
                    "rejection_reason": f"In cooldown: {cooldown_remaining:.1f} hours remaining",
                    "cooldown_remaining_hours": cooldown_remaining,
                },
            )
            if self.event_bus is not None:
                self.event_bus.publish(cooldown_event)

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "decision_rhythm.CooldownEventHandler"
