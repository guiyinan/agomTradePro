"""
Alpha Trigger Event Subscribers.

注册 Alpha Trigger 模块的事件订阅器到全局注册表。

重构说明 (2026-03-11):
- 通过 registry 实现反向依赖
- 在 apps.py 中自动注册
- 移除直接导入 handlers 到 EventBusInitializer
"""

import logging
from typing import Callable, Dict

from apps.events.domain.registry import get_event_subscriber_registry
from apps.events.domain.entities import EventType

logger = logging.getLogger(__name__)


def register_subscribers() -> None:
    """
    注册 Alpha Trigger 事件订阅器

    在 Django app ready() 时自动调用此方法。
    """
    try:
        registry = get_event_subscriber_registry()

        # 注册 Alpha 触发器主处理器 - 响应信号创建/批准和宏观变化
        registry.register(
            module_name="alpha_trigger",
            event_type=EventType.SIGNAL_CREATED,
            handler_factory=_create_alpha_trigger_handler,
            priority=80,
            description="Auto-create alpha triggers from signals"
        )

        registry.register(
            module_name="alpha_trigger",
            event_type=EventType.SIGNAL_APPROVED,
            handler_factory=_create_alpha_trigger_handler,
            priority=80,
            description="Activate triggers when signals approved"
        )

        registry.register(
            module_name="alpha_trigger",
            event_type=EventType.REGIME_CHANGED,
            handler_factory=_create_alpha_trigger_handler,
            priority=80,
            description="Evaluate regime-based triggers"
        )

        registry.register(
            module_name="alpha_trigger",
            event_type=EventType.POLICY_LEVEL_CHANGED,
            handler_factory=_create_alpha_trigger_handler,
            priority=80,
            description="Evaluate policy-based triggers"
        )

        # 注册候选晋升处理器 - 响应触发器发射事件
        registry.register(
            module_name="alpha_trigger",
            event_type=EventType.ALPHA_TRIGGER_FIRED,
            handler_factory=_create_candidate_promotion_handler,
            priority=70,
            description="Promote candidates based on trigger strength"
        )

        logger.info("Alpha Trigger subscribers registered successfully")

    except Exception as e:
        logger.error(f"Failed to register Alpha Trigger subscribers: {e}")


def _create_alpha_trigger_handler():
    """创建 Alpha 触发器处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.alpha_trigger.application.handlers import AlphaTriggerEventHandler
        from apps.alpha_trigger.application.use_cases import CreateTriggerUseCase

        # 获取用例实例
        create_use_case = CreateTriggerUseCase()

        return AlphaTriggerEventHandler(
            create_trigger_use_case=create_use_case,
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create AlphaTriggerEventHandler: {e}")
        raise


def _create_candidate_promotion_handler():
    """创建候选晋升处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.alpha_trigger.application.handlers import CandidatePromotionHandler
        from apps.alpha_trigger.infrastructure.repositories import AlphaCandidateRepository

        candidate_repository = AlphaCandidateRepository()

        return CandidatePromotionHandler(
            candidate_repository=candidate_repository,
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create CandidatePromotionHandler: {e}")
        raise


def get_handler_factories() -> Dict[EventType, Callable]:
    """
    获取处理器工厂

    Returns:
        {事件类型: 处理器工厂} 字典
    """
    return {
        EventType.SIGNAL_CREATED: _create_alpha_trigger_handler,
        EventType.SIGNAL_APPROVED: _create_alpha_trigger_handler,
        EventType.REGIME_CHANGED: _create_alpha_trigger_handler,
        EventType.POLICY_LEVEL_CHANGED: _create_alpha_trigger_handler,
        EventType.ALPHA_TRIGGER_FIRED: _create_candidate_promotion_handler,
    }
