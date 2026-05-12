"""
证伪规则 Domain 层

只使用 Python 标准库，定义核心业务逻辑。

架构说明：
- InvalidationCondition: 单个证伪条件
- InvalidationRule: 证伪规则（包含多个条件 + 逻辑操作符）
- InvalidationCheckResult: 证伪检查结果
- IndicatorValue: 指标值
- evaluate_rule(): 评估证伪规则的纯函数
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class ComparisonOperator(Enum):
    """比较操作符"""
    LT = "lt"      # 小于
    LTE = "lte"    # 小于等于
    GT = "gt"      # 大于
    GTE = "gte"    # 大于等于
    EQ = "eq"      # 等于


class LogicOperator(Enum):
    """逻辑操作符"""
    AND = "AND"
    OR = "OR"


class IndicatorType(Enum):
    """指标类型"""
    MACRO = "macro"       # 宏观指标（PMI、CPI等）
    MARKET = "market"     # 市场指标（指数、利率等）
    CUSTOM = "custom"     # 自定义指标


@dataclass(frozen=True)
class InvalidationCondition:
    """证伪条件

    定义什么条件下信号应该被证伪。

    Attributes:
        indicator_code: 指标代码（如 CN_PMI_MANUFACTURING）
        indicator_type: 指标类型（宏观/市场/自定义）
        operator: 比较操作符（小于/大于/等于等）
        threshold: 阈值
        duration: 持续期数（可选，如连续2期）
        compare_with: 比较对象（可选，如 prev_value 表示与前值比较）
    """
    indicator_code: str           # 指标代码
    indicator_type: IndicatorType # 指标类型
    operator: ComparisonOperator  # 比较操作符
    threshold: float              # 阈值
    duration: int | None = None      # 持续期数（可选）
    compare_with: str | None = None  # 比较对象（可选）

    def __post_init__(self):
        """验证条件有效性"""
        if self.duration is not None and self.duration < 1:
            raise ValueError("duration 必须大于 0")
        if self.compare_with not in (None, "prev_value", "prev_period"):
            raise ValueError(f"不支持的 compare_with: {self.compare_with}")

    def to_dict(self) -> dict:
        """转换为字典格式（用于存储）"""
        return {
            "indicator_code": self.indicator_code,
            "indicator_type": self.indicator_type.value,
            "operator": self.operator.value,
            "threshold": self.threshold,
            "duration": self.duration,
            "compare_with": self.compare_with,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InvalidationCondition":
        """从字典创建"""
        return cls(
            indicator_code=d["indicator_code"],
            indicator_type=IndicatorType(d["indicator_type"]),
            operator=ComparisonOperator(d["operator"]),
            threshold=d["threshold"],
            duration=d.get("duration"),
            compare_with=d.get("compare_with"),
        )


@dataclass(frozen=True)
class InvalidationRule:
    """证伪规则

    包含多个条件和逻辑操作符。

    Attributes:
        conditions: 条件列表
        logic: 逻辑操作符（AND/OR）
    """
    conditions: list[InvalidationCondition]
    logic: LogicOperator

    def __post_init__(self):
        """验证规则有效性"""
        if not self.conditions:
            raise ValueError("conditions 不能为空")

    def to_dict(self) -> dict:
        """转换为字典格式（用于存储）"""
        return {
            "conditions": [c.to_dict() for c in self.conditions],
            "logic": self.logic.value
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InvalidationRule":
        """从字典创建（用于加载）"""
        conditions = [
            InvalidationCondition.from_dict(c)
            for c in d["conditions"]
        ]
        return cls(
            conditions=conditions,
            logic=LogicOperator(d["logic"])
        )

    @property
    def human_readable(self) -> str:
        """生成人类可读的描述"""
        op_map = {
            ComparisonOperator.LT: "<",
            ComparisonOperator.LTE: "≤",
            ComparisonOperator.GT: ">",
            ComparisonOperator.GTE: "≥",
            ComparisonOperator.EQ: "=",
        }

        parts = []
        for cond in self.conditions:
            text = f"{cond.indicator_code} {op_map[cond.operator]} {cond.threshold}"
            if cond.duration:
                text += f" 连续{cond.duration}期"
            if cond.compare_with:
                text += f" (较{cond.compare_with})"
            parts.append(text)

        return f"当{'当'.join(parts)}时证伪"


@dataclass(frozen=True)
class InvalidationCheckResult:
    """证伪检查结果"""
    is_invalidated: bool
    reason: str
    checked_conditions: list[dict]  # 每个条件的检查详情
    checked_at: str  # ISO 格式时间戳


@dataclass
class IndicatorValue:
    """指标值

    包含当前值、历史值和元数据。
    """
    code: str
    current_value: float | None
    history_values: list[float]
    unit: str
    last_updated: str | None


# ==================== 纯函数业务逻辑 ====================

def _compare(value: float, op: ComparisonOperator, threshold: float) -> bool:
    """执行比较操作

    Args:
        value: 实际值
        op: 比较操作符
        threshold: 阈值

    Returns:
        bool: 比较结果
    """
    if op == ComparisonOperator.LT:
        return value < threshold
    elif op == ComparisonOperator.LTE:
        return value <= threshold
    elif op == ComparisonOperator.GT:
        return value > threshold
    elif op == ComparisonOperator.GTE:
        return value >= threshold
    elif op == ComparisonOperator.EQ:
        return abs(value - threshold) < 0.001
    return False


def evaluate_condition(
    condition: InvalidationCondition,
    indicator_value: IndicatorValue
) -> tuple[bool, dict]:
    """评估单个条件是否满足

    Args:
        condition: 证伪条件
        indicator_value: 指标值

    Returns:
        Tuple[bool, Dict]: (是否满足, 详细信息)
    """
    # 检查数据可用性
    if indicator_value.current_value is None:
        return False, {
            "error": "指标当前值不可用",
            "indicator_code": condition.indicator_code
        }

    actual_value = indicator_value.current_value

    # 处理 compare_with
    if condition.compare_with == "prev_value":
        if len(indicator_value.history_values) < 1:
            return False, {"error": "缺少历史值"}
        prev = indicator_value.history_values[0]
        actual_value = actual_value - prev

    # 执行比较
    result = _compare(actual_value, condition.operator, condition.threshold)

    # 检查持续期
    duration_met = True
    if result and condition.duration:
        if len(indicator_value.history_values) < condition.duration:
            duration_met = False
        else:
            consecutive_count = 0
            # 检查连续N期是否都满足条件
            for i, val in enumerate([indicator_value.current_value] + indicator_value.history_values):
                if i >= condition.duration:
                    break
                if _compare(val, condition.operator, condition.threshold):
                    consecutive_count += 1
                else:
                    break
            duration_met = consecutive_count >= condition.duration

    return result and duration_met, {
        "indicator_code": condition.indicator_code,
        "operator": condition.operator.value,
        "threshold": condition.threshold,
        "actual_value": actual_value,
        "is_met": result and duration_met,
    }


def _generate_invalidation_reason(
    rule: InvalidationRule,
    checked_conditions: list[dict]
) -> str:
    """生成证伪原因描述"""
    parts = []
    for cond, detail in zip(rule.conditions, checked_conditions):
        if not detail.get("is_met"):
            continue
        op_map = {
            ComparisonOperator.LT: "<",
            ComparisonOperator.LTE: "≤",
            ComparisonOperator.GT: ">",
            ComparisonOperator.GTE: "≥",
            ComparisonOperator.EQ: "=",
        }
        parts.append(
            f"{cond.indicator_code}={detail.get('actual_value')}"
            f" {op_map[cond.operator]} {cond.threshold}"
        )

    logic_text = " 且 " if rule.logic == LogicOperator.AND else " 或 "
    return f"证伪条件满足: {logic_text.join(parts)}"


def evaluate_rule(
    rule: InvalidationRule,
    indicator_values: dict[str, IndicatorValue]
) -> InvalidationCheckResult:
    """评估证伪规则

    根据指标值判断是否满足证伪条件。

    Args:
        rule: 证伪规则
        indicator_values: 指标值字典 {code: IndicatorValue}

    Returns:
        InvalidationCheckResult: 检查结果
    """
    checked_conditions = []
    results = []

    for cond in rule.conditions:
        ind_value = indicator_values.get(cond.indicator_code)
        if ind_value is None:
            is_met, detail = False, {
                "error": f"指标 {cond.indicator_code} 数据不可用"
            }
        else:
            is_met, detail = evaluate_condition(cond, ind_value)

        checked_conditions.append(detail)
        results.append(is_met)

    # 根据 logic 判断整体结果
    if rule.logic == LogicOperator.AND:
        is_invalidated = all(results)
    else:
        is_invalidated = any(results)

    if is_invalidated:
        reason = _generate_invalidation_reason(rule, checked_conditions)
    else:
        reason = "证伪条件未满足"

    return InvalidationCheckResult(
        is_invalidated=is_invalidated,
        reason=reason,
        checked_conditions=checked_conditions,
        checked_at=datetime.now(UTC).isoformat()
    )


def validate_rule(rule: InvalidationRule) -> list[str]:
    """验证规则的有效性

    Args:
        rule: 待验证的规则

    Returns:
        List[str]: 错误列表，空列表表示验证通过
    """
    errors = []

    if not rule.conditions:
        errors.append("规则不能为空")

    for i, cond in enumerate(rule.conditions):
        if not cond.indicator_code:
            errors.append(f"条件 {i}: indicator_code 不能为空")
        if cond.duration is not None and cond.duration < 1:
            errors.append(f"条件 {i}: duration 必须大于 0")
        if cond.compare_with not in (None, "prev_value", "prev_period"):
            errors.append(f"条件 {i}: 不支持的 compare_with: {cond.compare_with}")

    return errors
