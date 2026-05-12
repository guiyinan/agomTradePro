"""
Alpha Trigger Event Handlers

处理外部事件，响应信号创建和 Regime/Policy 变化。
"""

import logging

from apps.events.domain.entities import DomainEvent, EventHandler, EventType, create_event

from ..domain.entities import SignalStrength, TriggerType

logger = logging.getLogger(__name__)


class AlphaTriggerEventHandler(EventHandler):
    """
    Alpha 触发器事件处理器

    响应信号创建事件，自动创建 Alpha 触发器。

    Attributes:
        create_trigger_use_case: 创建触发器用例
        event_bus: 事件总线（用于发布后续事件）

    Example:
        >>> handler = AlphaTriggerEventHandler(create_use_case, event_bus)
        >>> handler.can_handle(EventType.SIGNAL_CREATED)  # True
    """

    def __init__(self, create_trigger_use_case=None, event_bus=None):
        """
        初始化处理器

        Args:
            create_trigger_use_case: 创建触发器用例（可选）
            event_bus: 事件总线（可选）
        """
        self.create_trigger_use_case = create_trigger_use_case
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type in [
            EventType.SIGNAL_CREATED,
            EventType.SIGNAL_APPROVED,
            EventType.REGIME_CHANGED,
            EventType.POLICY_LEVEL_CHANGED,
        ]

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        try:
            if event.event_type == EventType.SIGNAL_CREATED:
                self._handle_signal_created(event)
            elif event.event_type == EventType.SIGNAL_APPROVED:
                self._handle_signal_approved(event)
            elif event.event_type == EventType.REGIME_CHANGED:
                self._handle_regime_changed(event)
            elif event.event_type == EventType.POLICY_LEVEL_CHANGED:
                self._handle_policy_changed(event)

        except Exception as e:
            logger.error(f"Error in AlphaTriggerEventHandler: {e}", exc_info=True)

    def _handle_signal_created(self, event: DomainEvent):
        """处理信号创建事件，自动创建 Alpha 触发器"""
        if self.create_trigger_use_case is None:
            logger.warning("No create_trigger_use_case configured")
            return

        from ..application.use_cases import CreateTriggerRequest

        signal_data = event.payload

        # 检查是否已有触发器
        asset_code = signal_data.get("asset_code")
        if not asset_code:
            return

        # 构建触发器创建请求
        request = CreateTriggerRequest(
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code=asset_code,
            asset_class=signal_data.get("asset_class", ""),
            direction=signal_data.get("direction", "LONG"),
            trigger_condition={
                "source_signal_id": signal_data.get("signal_id"),
            },
            invalidation_conditions=signal_data.get("invalidation_conditions", []),
            confidence=signal_data.get("confidence", 0.5),
            thesis=signal_data.get("logic_desc", ""),
            related_regime=signal_data.get("target_regime"),
        )

        # 创建触发器
        response = self.create_trigger_use_case.execute(request)

        if response.success:
            logger.info(
                f"Alpha trigger auto-created from signal: "
                f"{response.trigger.trigger_id}"
            )
        else:
            logger.warning(f"Failed to create trigger: {response.error}")

    def _handle_signal_approved(self, event: DomainEvent):
        """处理信号批准事件"""
        # 批准的信号可以激活对应的触发器
        signal_id = event.get_payload_value("signal_id")
        logger.info(f"Signal {signal_id} approved, activating corresponding trigger")

        # 可以在这里触发触发器激活逻辑

    def _handle_regime_changed(self, event: DomainEvent):
        """处理 Regime 变化事件"""
        new_regime = event.get_payload_value("new_regime")
        old_regime = event.get_payload_value("old_regime")

        logger.info(f"Regime changed from {old_regime} to {new_regime}")

        # Regime 变化可能触发 Regime 转换类型的触发器
        # 也可能影响其他触发器的有效性

        # 发布评估事件
        if self.event_bus:
            evaluate_event = create_event(
                event_type=EventType.ALPHA_TRIGGER_ACTIVATED,
                payload={
                    "reason": "regime_changed",
                    "old_regime": old_regime,
                    "new_regime": new_regime,
                    "action": "evaluate_regime_triggers",
                },
            )
            self.event_bus.publish(evaluate_event)

    def _handle_policy_changed(self, event: DomainEvent):
        """处理 Policy 变化事件"""
        old_level = event.get_payload_value("old_level")
        new_level = event.get_payload_value("new_level")

        logger.info(f"Policy level changed from P{old_level} to P{new_level}")

        # Policy 变化可能触发 Policy 变化类型的触发器

        if self.event_bus:
            evaluate_event = create_event(
                event_type=EventType.ALPHA_TRIGGER_ACTIVATED,
                payload={
                    "reason": "policy_changed",
                    "old_level": old_level,
                    "new_level": new_level,
                    "action": "evaluate_policy_triggers",
                },
            )
            self.event_bus.publish(evaluate_event)

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "alpha_trigger.AlphaTriggerEventHandler"


class TriggerInvalidationHandler(EventHandler):
    """
    触发器证伪处理器

    定时检查触发器的证伪条件。

    Attributes:
        check_invalidation_use_case: 检查证伪用例
        event_bus: 事件总线

    Example:
        >>> handler = TriggerInvalidationHandler(check_use_case, event_bus)
        >>> handler.can_handle(EventType.ALPHA_TRIGGER_ACTIVATED)  # True
    """

    def __init__(self, check_invalidation_use_case, event_bus):
        """
        初始化处理器

        Args:
            check_invalidation_use_case: 检查证伪用例
            event_bus: 事件总线
        """
        self.check_invalidation_use_case = check_invalidation_use_case
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        # 可以定时触发，或者响应特定事件
        return event_type in [
            EventType.ALPHA_TRIGGER_TRIGGERED,
            EventType.REGIME_CHANGED,
            EventType.POLICY_LEVEL_CHANGED,
        ]

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        try:
            # 当环境变化时，检查所有活跃触发器是否证伪
            if event.event_type in [EventType.REGIME_CHANGED, EventType.POLICY_LEVEL_CHANGED]:
                self._check_all_active_triggers(event)

        except Exception as e:
            logger.error(f"Error in TriggerInvalidationHandler: {e}", exc_info=True)

    def _check_all_active_triggers(self, event: DomainEvent):
        """检查所有活跃触发器"""
        # 获取当前环境信息
        event.get_payload_value("new_regime")
        event.get_payload_value("new_level")

        logger.info("Checking all active triggers for invalidation")

        # 这里需要获取所有活跃触发器并逐个检查
        # 实际实现需要注入 trigger_repository

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "alpha_trigger.TriggerInvalidationHandler"


class CandidatePromotionHandler(EventHandler):
    """
    候选提升处理器

    处理 Alpha 候选的状态提升（从 WATCH -> CANDIDATE -> ACTIONABLE）。

    Attributes:
        candidate_repository: 候选仓储
        event_bus: 事件总线

    Example:
        >>> handler = CandidatePromotionHandler(candidate_repo, event_bus)
        >>> handler.can_handle(EventType.ALPHA_TRIGGER_FIRED)  # True
    """

    def __init__(self, candidate_repository, event_bus):
        """
        初始化处理器

        Args:
            candidate_repository: 候选仓储
            event_bus: 事件总线
        """
        self.candidate_repository = candidate_repository
        self.event_bus = event_bus

    def can_handle(self, event_type: EventType) -> bool:
        """判断是否能处理该类型的事件"""
        return event_type == EventType.ALPHA_TRIGGER_FIRED

    def handle(self, event: DomainEvent) -> None:
        """处理事件"""
        try:
            trigger_id = event.get_payload_value("trigger_id")
            event.get_payload_value("asset_code")
            strength = event.get_payload_value("strength")

            # 根据信号强度决定候选状态
            if strength in [SignalStrength.VERY_STRONG.value, SignalStrength.STRONG.value]:
                new_status = "ACTIONABLE"
            elif strength == SignalStrength.MODERATE.value:
                new_status = "CANDIDATE"
            else:
                new_status = "WATCH"

            # 更新候选状态
            candidate = self.candidate_repository.get_by_trigger_id(trigger_id)
            if candidate:
                updated = self.candidate_repository.update_status(
                    candidate.candidate_id,
                    new_status,
                )

                # 发布状态变更事件
                if self.event_bus:
                    status_event = create_event(
                        event_type=EventType.SIGNAL_TRIGGERED,
                        payload={
                            "candidate_id": updated.candidate_id,
                            "asset_code": updated.asset_code,
                            "old_status": candidate.status,
                            "new_status": new_status,
                        },
                    )
                    self.event_bus.publish(status_event)

                logger.info(
                    f"Candidate {updated.candidate_id} promoted to {new_status}"
                )

        except Exception as e:
            logger.error(f"Error in CandidatePromotionHandler: {e}", exc_info=True)

    def get_handler_id(self) -> str:
        """获取处理器标识符"""
        return "alpha_trigger.CandidatePromotionHandler"
