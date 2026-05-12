"""
Beta Gate Module

硬闸门过滤模块。

通过 Regime + Policy + 风险画像的组合约束，实现资产的"可见性裁剪"。
"""

from .domain import (
    BetaGateEvaluator,
    GateConfig,
    GateConfigSelector,
    GateDecision,
    GateStatus,
    PolicyConstraint,
    PortfolioConstraint,
    RegimeConstraint,
    RiskProfile,
    VisibilityUniverse,
    VisibilityUniverseBuilder,
    build_universe,
    create_gate_config,
    evaluate_visibility,
    get_default_configs,
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

# Import admin to ensure it's loaded when Django starts
default_app_config = 'beta_gate.apps.BetaGateConfig'
