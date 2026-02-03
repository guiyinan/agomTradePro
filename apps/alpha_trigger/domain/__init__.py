"""
Alpha Trigger Domain Module

Alpha 事件触发的 Domain 层。

实现离散、可证伪、可行动的 Alpha 信号触发机制。
"""

from .entities import (
    # 枚举
    TriggerType,
    TriggerStatus,
    SignalStrength,
    # 实体
    InvalidationCondition,
    AlphaTrigger,
    TriggerEvent,
    AlphaCandidate,
    TriggerConfig,
    # 工厂函数
    create_invalidations,
    calculate_strength,
)

from .services import (
    # 结果类型
    InvalidationCheckResult,
    # 服务
    TriggerEvaluator,
    TriggerInvalidator,
    CandidateGenerator,
    TriggerFilter,
    # 便捷函数
    evaluate_trigger,
    check_invalidations,
    generate_candidate,
)

__all__ = [
    # 枚举
    "TriggerType",
    "TriggerStatus",
    "SignalStrength",
    # 实体
    "InvalidationCondition",
    "AlphaTrigger",
    "TriggerEvent",
    "AlphaCandidate",
    "TriggerConfig",
    # 工厂函数
    "create_invalidations",
    "calculate_strength",
    # 结果类型
    "InvalidationCheckResult",
    # 服务
    "TriggerEvaluator",
    "TriggerInvalidator",
    "CandidateGenerator",
    "TriggerFilter",
    # 便捷函数
    "evaluate_trigger",
    "check_invalidations",
    "generate_candidate",
]
