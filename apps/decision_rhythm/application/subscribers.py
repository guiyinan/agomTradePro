"""
Decision Rhythm Event Subscribers.

注册 Decision Rhythm 模块的事件订阅器到全局注册表。

重构说明 (2026-03-11):
- 通过 registry 实现反向依赖
- 在 apps.py 中自动注册
- 移除直接导入 handlers 到 EventBusInitializer
"""

import logging
from collections.abc import Callable

from apps.events.domain.entities import EventType
from apps.events.domain.registry import get_event_subscriber_registry

logger = logging.getLogger(__name__)


def register_subscribers() -> None:
    """
    注册 Decision Rhythm 事件订阅器

    在 Django app ready() 时自动调用此方法。
    """
    try:
        registry = get_event_subscriber_registry()

        # 注册决策节奏主处理器 - 响应决策和触发器事件
        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.DECISION_APPROVED,
            handler_factory=_create_decision_rhythm_handler,
            priority=60,
            description="Update quota and cooldown on decision approval"
        )

        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.DECISION_REJECTED,
            handler_factory=_create_decision_rhythm_handler,
            priority=60,
            description="Handle decision rejection"
        )

        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.ALPHA_TRIGGER_FIRED,
            handler_factory=_create_decision_rhythm_handler,
            priority=60,
            description="Update rhythm on trigger fired"
        )

        # 注册配额监控处理器
        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.DECISION_APPROVED,
            handler_factory=_create_quota_monitor_handler,
            priority=50,
            description="Monitor quota usage and emit warnings"
        )

        # 注册冷却期处理器
        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.DECISION_APPROVED,
            handler_factory=_create_cooldown_handler,
            priority=55,
            description="Manage asset cooldown periods"
        )

        registry.register(
            module_name="decision_rhythm",
            event_type=EventType.SIGNAL_TRIGGERED,
            handler_factory=_create_cooldown_handler,
            priority=55,
            description="Check cooldown on signal trigger"
        )

        logger.debug("Decision Rhythm subscribers registered successfully")

    except Exception as e:
        logger.error(f"Failed to register Decision Rhythm subscribers: {e}")


def _create_decision_rhythm_handler():
    """创建决策节奏处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.decision_rhythm.application.handlers import DecisionRhythmEventHandler

        return DecisionRhythmEventHandler(
            quota_manager=None,  # 使用默认
            cooldown_manager=None,  # 使用默认
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create DecisionRhythmEventHandler: {e}")
        raise


def _create_quota_monitor_handler():
    """创建配额监控处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.decision_rhythm.application.handlers import QuotaMonitorHandler
        from apps.decision_rhythm.domain.services import QuotaManager

        quota_manager = QuotaManager()

        return QuotaMonitorHandler(
            quota_manager=quota_manager,
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create QuotaMonitorHandler: {e}")
        raise


def _create_cooldown_handler():
    """创建冷却期处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.decision_rhythm.application.handlers import CooldownEventHandler
        from apps.decision_rhythm.domain.services import CooldownManager

        cooldown_manager = CooldownManager()

        return CooldownEventHandler(
            cooldown_manager=cooldown_manager,
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create CooldownEventHandler: {e}")
        raise


def get_handler_factories() -> dict[EventType, Callable]:
    """
    获取处理器工厂

    Returns:
        {事件类型: 处理器工厂} 字典
    """
    return {
        EventType.DECISION_APPROVED: _create_decision_rhythm_handler,
        EventType.DECISION_REJECTED: _create_decision_rhythm_handler,
        EventType.ALPHA_TRIGGER_FIRED: _create_decision_rhythm_handler,
        EventType.SIGNAL_TRIGGERED: _create_cooldown_handler,
    }
