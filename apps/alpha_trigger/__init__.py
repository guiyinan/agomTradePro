"""
Alpha Trigger Module

Alpha 事件触发模块。

实现离散、可证伪、可行动的 Alpha 信号触发机制。
"""

from .domain import (
    AlphaCandidate,
    AlphaTrigger,
    CandidateGenerator,
    InvalidationCheckResult,
    InvalidationCondition,
    SignalStrength,
    TriggerConfig,
    TriggerEvaluator,
    TriggerEvent,
    TriggerFilter,
    TriggerInvalidator,
    TriggerStatus,
    TriggerType,
    calculate_strength,
    check_invalidations,
    create_invalidations,
    evaluate_trigger,
    generate_candidate,
)

__all__ = [
    "TriggerType",
    "TriggerStatus",
    "SignalStrength",
    "InvalidationCondition",
    "AlphaTrigger",
    "TriggerEvent",
    "AlphaCandidate",
    "TriggerConfig",
    "create_invalidations",
    "calculate_strength",
    "InvalidationCheckResult",
    "TriggerEvaluator",
    "TriggerInvalidator",
    "CandidateGenerator",
    "TriggerFilter",
    "evaluate_trigger",
    "check_invalidations",
    "generate_candidate",
]
