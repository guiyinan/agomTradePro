"""
Dashboard Domain Rules

仪表盘领域规则定义。
仅使用 Python 标准库，不依赖 Django、pandas 等外部库。
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .entities import (
    AlertConfig,
    AlertSeverity,
    CardType,
    DashboardCard,
    DashboardLayout,
    DashboardWidget,
    MetricCard,
)


class Rule(ABC):
    """规则基类"""

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估规则

        Args:
            context: 上下文数据

        Returns:
            是否通过规则
        """
        pass


@dataclass(frozen=True)
class DashboardCardVisibilityRule(Rule):
    """
    仪表盘卡片可见性规则

    根据用户权限、环境状态等条件判断卡片是否可见。

    Attributes:
        card_id: 卡片ID
        conditions: 可见性条件
    """

    card_id: str
    conditions: dict[str, Any]

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估卡片是否可见

        Args:
            context: 上下文，包含：
                - user_permissions: 用户权限列表
                - current_regime: 当前 Regime
                - policy_level: 政策档位
                - has_alpha: 是否有 Alpha 数据
                - has_beta_gate: 是否启用 Beta Gate
                - has_decision_rhythm: 是否启用决策节奏

        Returns:
            是否可见
        """
        # 默认可见
        if not self.conditions:
            return True

        # 检查权限条件
        if "required_permissions" in self.conditions:
            required = self.conditions["required_permissions"]
            user_permissions = context.get("user_permissions", [])
            if not any(p in user_permissions for p in required):
                return False

        # 检查 Regime 条件
        if "required_regimes" in self.conditions:
            required_regimes = self.conditions["required_regimes"]
            current_regime = context.get("current_regime")
            if current_regime not in required_regimes:
                return False

        # 检查功能开关条件
        if "requires_alpha" in self.conditions and self.conditions["requires_alpha"]:
            if not context.get("has_alpha", False):
                return False

        if "requires_beta_gate" in self.conditions and self.conditions["requires_beta_gate"]:
            if not context.get("has_beta_gate", False):
                return False

        if "requires_decision_rhythm" in self.conditions and self.conditions["requires_decision_rhythm"]:
            if not context.get("has_decision_rhythm", False):
                return False

        # 检查数据可用性条件
        if "requires_data_source" in self.conditions:
            data_sources = self.conditions["requires_data_source"]
            available_data = context.get("available_data", {})
            for source in data_sources:
                if not available_data.get(source):
                    return False

        return True


@dataclass(frozen=True)
class WidgetPositionRule(Rule):
    """
    组件位置规则

    验证组件位置是否合法。

    Attributes:
        max_columns: 最大列数
        max_rows: 最大行数
        min_width: 最小宽度
        min_height: 最小高度
    """

    max_columns: int = 12
    max_rows: int = 100
    min_width: int = 1
    min_height: int = 1

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估组件位置是否合法

        Args:
            context: 上下文，包含 position 和 size

        Returns:
            是否合法
        """
        position = context.get("position", {})
        size = context.get("size", {})

        row = position.get("row", 0)
        col = position.get("col", 0)
        width = size.get("width", 1)
        height = size.get("height", 1)

        # 检查边界
        if row < 0 or row >= self.max_rows:
            return False
        if col < 0 or col >= self.max_columns:
            return False
        if width < self.min_width or width > self.max_columns:
            return False
        if height < self.min_height:
            return False

        # 检查是否超出边界
        if col + width > self.max_columns:
            return False

        return True


@dataclass(frozen=True)
class MetricThresholdRule(Rule):
    """
    指标阈值规则

    根据阈值判断指标的状态。

    Attributes:
        metric_name: 指标名称
        warning_threshold: 警告阈值
        critical_threshold: 严重阈值
        operator: 比较操作符（gt, lt, gte, lte, eq）
    """

    metric_name: str
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    operator: str = "gte"  # greater than or equal

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估指标是否超过阈值

        Args:
            context: 上下文，包含指标值

        Returns:
            是否超过阈值（警告或严重）
        """
        value = context.get(self.metric_name)
        if value is None:
            return False

        try:
            value = float(value)
        except (TypeError, ValueError):
            return False

        return self._check_threshold(value)

    def _check_threshold(self, value: float) -> bool:
        """检查阈值"""
        if self.critical_threshold is not None:
            if self._compare(value, self.critical_threshold):
                return True

        if self.warning_threshold is not None:
            if self._compare(value, self.warning_threshold):
                return True

        return False

    def _compare(self, value: float, threshold: float) -> bool:
        """根据操作符比较"""
        ops = {
            "gt": lambda a, b: a > b,
            "lt": lambda a, b: a < b,
            "gte": lambda a, b: a >= b,
            "lte": lambda a, b: a <= b,
            "eq": lambda a, b: a == b,
        }
        op_func = ops.get(self.operator, lambda a, b: a >= b)
        return op_func(value, threshold)

    def get_severity(self, context: dict[str, Any]) -> AlertSeverity | None:
        """
        获取告警级别

        Args:
            context: 上下文

        Returns:
            告警级别
        """
        value = context.get(self.metric_name)
        if value is None:
            return None

        try:
            value = float(value)
        except (TypeError, ValueError):
            return None

        if self.critical_threshold is not None and self._compare(value, self.critical_threshold):
            return AlertSeverity.CRITICAL

        if self.warning_threshold is not None and self._compare(value, self.warning_threshold):
            return AlertSeverity.WARNING

        return None


@dataclass(frozen=True)
class CardDependencyRule(Rule):
    """
    卡片依赖规则

    检查卡片的依赖是否满足。

    Attributes:
        card_id: 卡片ID
        dependencies: 依赖的卡片ID列表
    """

    card_id: str
    dependencies: list[str]

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估依赖是否满足

        Args:
            context: 上下文，包含 available_cards

        Returns:
            依赖是否满足
        """
        available_cards = context.get("available_cards", set())

        # 检查所有依赖是否可用
        for dep_id in self.dependencies:
            if dep_id not in available_cards:
                return False

        return True


@dataclass(frozen=True)
class RefreshIntervalRule(Rule):
    """
    刷新间隔规则

    验证刷新间隔是否合理。

    Attributes:
        min_interval: 最小间隔（秒）
        max_interval: 最大间隔（秒）
    """

    min_interval: int = 10
    max_interval: int = 3600

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估刷新间隔是否合理

        Args:
            context: 上下文，包含 interval

        Returns:
            是否合理
        """
        interval = context.get("interval", 60)

        try:
            interval = int(interval)
        except (TypeError, ValueError):
            return False

        return self.min_interval <= interval <= self.max_interval


@dataclass(frozen=True)
class DataSourceAvailabilityRule(Rule):
    """
    数据源可用性规则

    检查数据源是否可用。

    Attributes:
        data_source: 数据源名称
        required_fields: 必需字段
    """

    data_source: str
    required_fields: list[str] = None

    def evaluate(self, context: dict[str, Any]) -> bool:
        """
        评估数据源是否可用

        Args:
            context: 上下文，包含 available_data

        Returns:
            是否可用
        """
        available_data = context.get("available_data", {})

        # 检查数据源是否存在
        if self.data_source not in available_data:
            return False

        # 检查必需字段
        if self.required_fields:
            data = available_data[self.data_source]
            if isinstance(data, dict):
                for field in self.required_fields:
                    if field not in data or data[field] is None:
                        return False

        return True


class RuleEngine:
    """
    规则引擎

    批量评估多个规则。

    Example:
        >>> engine = RuleEngine()
        >>> engine.add_rule(DashboardCardVisibilityRule(...))
        >>> engine.add_rule(DataSourceAvailabilityRule(...))
        >>> results = engine.evaluate_all(context)
    """

    def __init__(self):
        """初始化规则引擎"""
        self._rules: list[Rule] = []

    def add_rule(self, rule: Rule) -> None:
        """
        添加规则

        Args:
            rule: 规则
        """
        self._rules.append(rule)

    def remove_rule(self, rule: Rule) -> None:
        """
        移除规则

        Args:
            rule: 规则
        """
        if rule in self._rules:
            self._rules.remove(rule)

    def evaluate_all(self, context: dict[str, Any]) -> dict[str, bool]:
        """
        评估所有规则

        Args:
            context: 上下文

        Returns:
            规则ID到结果的映射
        """
        results = {}
        for rule in self._rules:
            rule_id = f"{rule.__class__.__name__}"
            results[rule_id] = rule.evaluate(context)
        return results

    def evaluate_any(self, context: dict[str, Any]) -> bool:
        """
        评估是否任意规则通过

        Args:
            context: 上下文

        Returns:
            是否有任意规则通过
        """
        return any(rule.evaluate(context) for rule in self._rules)

    def evaluate_all_pass(self, context: dict[str, Any]) -> bool:
        """
        评估是否所有规则都通过

        Args:
            context: 上下文

        Returns:
            是否所有规则都通过
        """
        return all(rule.evaluate(context) for rule in self._rules)

    def clear(self) -> None:
        """清空所有规则"""
        self._rules.clear()
