"""
Beta Gate Event Subscribers.

注册 Beta Gate 模块的事件订阅器到全局注册表。

重构说明 (2026-03-11):
- 通过 registry 实现反向依赖
- 在 apps.py 中自动注册
- 移除直接导入 handlers 到 EventBusInitializer
"""

import logging
from collections.abc import Callable
from typing import Dict

from apps.events.domain.entities import EventType
from apps.events.domain.registry import SubscriberInfo, get_event_subscriber_registry

logger = logging.getLogger(__name__)


def register_subscribers() -> None:
    """
    注册 Beta Gate 事件订阅器

    在 Django app ready() 时自动调用此方法。
    """
    try:
        registry = get_event_subscriber_registry()

        # 注册 Beta Gate 主处理器
        registry.register(
            module_name="beta_gate",
            event_type=EventType.REGIME_CHANGED,
            handler_factory=_create_beta_gate_handler,
            priority=100
        )

        # 注册 Gate 失效处理器
        registry.register(
            module_name="beta_gate",
            event_type=EventType.POLICY_LEVEL_CHANGED,
            handler_factory=_create_gate_invalidation_handler,
            priority=90
        )

        logger.debug("Beta Gate subscribers registered successfully")

    except Exception as e:
        logger.error(f"Failed to register Beta Gate subscribers: {e}")


def _create_beta_gate_handler():
    """创建 Beta Gate 处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.beta_gate.application.handlers import BetaGateEventHandler
        from apps.beta_gate.domain.entities import get_default_configs
        from apps.beta_gate.domain.services import GateConfigSelector, VisibilityUniverseBuilder

        return BetaGateEventHandler(
            universe_builder=VisibilityUniverseBuilder(),
            config_selector=GateConfigSelector(get_default_configs()),
            event_bus=None  # 将被注入
        )
    except Exception as e:
        logger.error(f"Failed to create BetaGateEventHandler: {e}")
        raise


def _create_gate_invalidation_handler():
    """创建 Gate 失效处理器"""
    try:
        # 延迟导入避免循环依赖
        from apps.beta_gate.application.handlers import GateInvalidationHandler
        from apps.beta_gate.domain.entities import get_default_configs
        from apps.beta_gate.domain.services import GateConfigSelector

        return GateInvalidationHandler(
            config_selector=GateConfigSelector(get_default_configs())
        )
    except Exception as e:
        logger.error(f"Failed to create GateInvalidationHandler: {e}")
        raise


def get_handler_factories() -> dict[EventType, Callable]:
    """
    获取处理器工厂

    Returns:
        {事件类型: 处理器工厂} 字典
    """
    return {
        EventType.REGIME_CHANGED: _create_beta_gate_handler,
        EventType.POLICY_LEVEL_CHANGED: _create_gate_invalidation_handler
    }
