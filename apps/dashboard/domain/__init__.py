"""
Dashboard Domain Layer

仪表盘领域层，包含仪表盘相关的业务实体、规则和服务。
"""

from .entities import (
    DashboardCard,
    DashboardWidget,
    DashboardLayout,
    ChartConfig,
    MetricCard,
    AlertConfig,
)
from .rules import (
    DashboardCardVisibilityRule,
    WidgetPositionRule,
    MetricThresholdRule,
)

__all__ = [
    "DashboardCard",
    "DashboardWidget",
    "DashboardLayout",
    "ChartConfig",
    "MetricCard",
    "AlertConfig",
    "DashboardCardVisibilityRule",
    "WidgetPositionRule",
    "MetricThresholdRule",
]
