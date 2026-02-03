"""
Beta Gate Module

硬闸门过滤模块。

通过 Regime + Policy + 风险画像的组合约束，实现资产的"可见性裁剪"。
"""

from .domain import (
    GateStatus,
    RiskProfile,
    RegimeConstraint,
    PolicyConstraint,
    PortfolioConstraint,
    GateDecision,
    GateConfig,
    VisibilityUniverse,
    create_gate_config,
    get_default_configs,
    BetaGateEvaluator,
    VisibilityUniverseBuilder,
    GateConfigSelector,
    evaluate_visibility,
    build_universe,
)

__all__ = [
    "GateStatus",
    "RiskProfile",
    "RegimeConstraint",
    "PolicyConstraint",
    "PortfolioConstraint",
    "GateDecision",
    "GateConfig",
    "VisibilityUniverse",
    "create_gate_config",
    "get_default_configs",
    "BetaGateEvaluator",
    "VisibilityUniverseBuilder",
    "GateConfigSelector",
    "evaluate_visibility",
    "build_universe",
]
