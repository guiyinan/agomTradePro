"""
Decision Rhythm Domain Module

决策频率约束和配额管理的 Domain 层。

实现稀疏决策的工程化约束。
"""

from .entities import (
    # 枚举
    DecisionPriority,
    QuotaPeriod,
    QuotaStatus,
    # 实体
    DecisionQuota,
    CooldownPeriod,
    DecisionRequest,
    DecisionResponse,
    RhythmConfig,
    # 工厂函数
    create_quota,
    create_cooldown,
    create_request,
    get_default_rhythm_config,
)

from .services import (
    # 检查结果
    QuotaCheckResult,
    CooldownCheckResult,
    # 服务
    QuotaManager,
    CooldownManager,
    RhythmManager,
    DecisionScheduler,
    # 便捷函数
    submit_decision_request,
    check_quota_status,
    check_cooldown_status,
)

__all__ = [
    # 枚举
    "DecisionPriority",
    "QuotaPeriod",
    "QuotaStatus",
    # 实体
    "DecisionQuota",
    "CooldownPeriod",
    "DecisionRequest",
    "DecisionResponse",
    "RhythmConfig",
    # 工厂函数
    "create_quota",
    "create_cooldown",
    "create_request",
    "get_default_rhythm_config",
    # 检查结果
    "QuotaCheckResult",
    "CooldownCheckResult",
    # 服务
    "QuotaManager",
    "CooldownManager",
    "RhythmManager",
    "DecisionScheduler",
    # 便捷函数
    "submit_decision_request",
    "check_quota_status",
    "check_cooldown_status",
]
