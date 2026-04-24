"""Compatibility re-exports for legacy strategy serializer imports."""

from importlib import import_module

__all__ = [
    "AIStrategyConfigSerializer",
    "PortfolioStrategyAssignmentDetailSerializer",
    "PortfolioStrategyAssignmentSerializer",
    "RuleConditionListSerializer",
    "RuleConditionSerializer",
    "ScriptConfigSerializer",
    "StrategyDetailSerializer",
    "StrategyExecutionLogListSerializer",
    "StrategyExecutionLogSerializer",
    "StrategySerializer",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module("apps.strategy.interface.serializers")
    return getattr(module, name)
