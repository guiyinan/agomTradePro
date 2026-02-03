"""
Beta Gate Domain Module

硬闸门过滤的 Domain 层。

通过 Regime + Policy + 风险画像的组合约束，实现资产的"可见性裁剪"。
"""

from .entities import (
    # 枚举
    GateStatus,
    RiskProfile,
    # 实体
    RegimeConstraint,
    PolicyConstraint,
    PortfolioConstraint,
    GateDecision,
    GateConfig,
    VisibilityUniverse,
    # 工厂函数
    create_gate_config,
    get_default_configs,
)

from .services import (
    # 服务
    BetaGateEvaluator,
    VisibilityUniverseBuilder,
    GateConfigSelector,
    # 便捷函数
    evaluate_visibility,
    build_universe,
)

__all__ = [
    # 枚举
    "GateStatus",
    "RiskProfile",
    # 实体
    "RegimeConstraint",
    "PolicyConstraint",
    "PortfolioConstraint",
    "GateDecision",
    "GateConfig",
    "VisibilityUniverse",
    # 工厂函数
    "create_gate_config",
    "get_default_configs",
    # 服务
    "BetaGateEvaluator",
    "VisibilityUniverseBuilder",
    "GateConfigSelector",
    # 便捷函数
    "evaluate_visibility",
    "build_universe",
]
