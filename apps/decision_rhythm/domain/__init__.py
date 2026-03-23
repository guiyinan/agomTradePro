"""
Decision Rhythm Domain Module

决策频率约束和配额管理的 Domain 层。

实现稀疏决策的工程化约束。
"""

from .entities import (
    CooldownPeriod,
    # 枚举
    DecisionPriority,
    # 实体
    DecisionQuota,
    DecisionRequest,
    DecisionResponse,
    QuotaPeriod,
    QuotaStatus,
    RhythmConfig,
    create_cooldown,
    # 工厂函数
    create_quota,
    create_request,
    get_default_rhythm_config,
)
from .services import (
    CooldownCheckResult,
    CooldownManager,
    DecisionScheduler,
    # 检查结果
    QuotaCheckResult,
    # 服务
    QuotaManager,
    RhythmManager,
    check_cooldown_status,
    check_quota_status,
    # 便捷函数
    submit_decision_request,
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
