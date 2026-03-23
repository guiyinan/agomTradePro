"""
规则评估器 - Application 层

遵循项目架构约束：
- 只使用 Domain 层的 Protocol 接口
- 不直接依赖 ORM Model
- 通过依赖注入获取数据
- 纯业务逻辑，无外部依赖
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from apps.strategy.domain.entities import RuleCondition, RuleType
from apps.strategy.domain.protocols import RuleEvaluatorProtocol

logger = logging.getLogger(__name__)


# ========================================================================
# 基础评估器
# ========================================================================

class BaseEvaluator(ABC):
    """评估器基类"""

    @abstractmethod
    def evaluate(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估条件是否满足

        Args:
            condition: 条件表达式（JSON 格式）
            context: 上下文数据

        Returns:
            是否满足条件
        """
        pass

    def _get_value(self, data: dict[str, Any], key: str, default: Any = None) -> Any:
        """
        安全获取嵌套字典中的值

        Args:
            data: 数据字典
            key: 键路径（支持点号分隔，如 'macro.pmi'）
            default: 默认值

        Returns:
            值或默认值
        """
        keys = key.split('.')
        value = data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default


# ========================================================================
# 宏观指标评估器
# ========================================================================

class MacroIndicatorEvaluator(BaseEvaluator):
    """
    宏观指标评估器

    支持的运算符：
    - >, <, >=, <=, ==, !=: 比较运算
    - between: 区间判断
    - trend: 趋势判断（连续N个周期的变化）

    示例：
    {
        "operator": ">",
        "indicator": "CN_PMI_MANUFACTURING",
        "threshold": 50
    }

    {
        "operator": "between",
        "indicator": "US_10Y_TREASURY_YIELD",
        "min": 3.0,
        "max": 5.0
    }

    {
        "operator": "trend",
        "indicator": "CN_CPI_YOY",
        "direction": "up",
        "periods": 3
    }
    """

    def evaluate(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估宏观指标条件

        Args:
            condition: 条件表达式
            context: 上下文数据（必须包含 'macro' 字段）

        Returns:
            是否满足条件
        """
        operator = self._normalize_operator(condition.get('operator'))
        indicator_code = condition.get('indicator')

        if not operator or not indicator_code:
            logger.warning(f"Invalid macro condition: {condition}")
            return False

        # 从上下文获取宏观指标数据
        macro_data = context.get('macro', {})
        indicator_value = self._get_value(macro_data, indicator_code)

        if indicator_value is None:
            logger.warning(f"Macro indicator not found: {indicator_code}")
            return False

        # 根据运算符进行评估
        try:
            if operator == '>':
                threshold = condition.get('threshold', 0)
                return float(indicator_value) > float(threshold)

            elif operator == '<':
                threshold = condition.get('threshold', 0)
                return float(indicator_value) < float(threshold)

            elif operator == '>=':
                threshold = condition.get('threshold', 0)
                return float(indicator_value) >= float(threshold)

            elif operator == '<=':
                threshold = condition.get('threshold', 0)
                return float(indicator_value) <= float(threshold)

            elif operator == '==':
                threshold = condition.get('threshold', 0)
                return abs(float(indicator_value) - float(threshold)) < 1e-6

            elif operator == '!=':
                threshold = condition.get('threshold', 0)
                return abs(float(indicator_value) - float(threshold)) >= 1e-6

            elif operator == 'between':
                # 兼容历史字段：min_value/max_value
                min_val = condition.get('min', condition.get('min_value', 0))
                max_val = condition.get('max', condition.get('max_value', 0))
                return float(min_val) <= float(indicator_value) <= float(max_val)

            elif operator == 'trend':
                return self._evaluate_trend(condition, macro_data)

            else:
                logger.warning(f"Unsupported operator: {operator}")
                return False

        except (ValueError, TypeError) as e:
            logger.error(f"Error evaluating macro condition: {e}, condition: {condition}")
            return False

    @staticmethod
    def _normalize_operator(operator: str | None) -> str | None:
        """兼容前端历史写法（gt/gte/eq...）"""
        mapping = {
            'gt': '>',
            'gte': '>=',
            'lt': '<',
            'lte': '<=',
            'eq': '==',
            'ne': '!=',
        }
        return mapping.get(operator, operator)

    def _evaluate_trend(self, condition: dict[str, Any], macro_data: dict[str, Any]) -> bool:
        """
        评估趋势条件

        Args:
            condition: 条件表达式
            macro_data: 宏观数据

        Returns:
            是否满足趋势条件
        """
        indicator_code = condition.get('indicator')
        direction = condition.get('direction', 'up')  # up, down
        periods = condition.get('periods', 2)  # 连续周期数

        # 获取历史数据（假设上下文中包含历史数据）
        history_key = f"{indicator_code}_history"
        history = macro_data.get(history_key, [])

        if len(history) < periods:
            logger.warning(f"Insufficient history data for trend: {indicator_code}")
            return False

        # 检查最近 N 个周期的趋势
        recent_values = history[-periods:]

        if direction == 'up':
            # 检查是否连续上升
            for i in range(1, len(recent_values)):
                if recent_values[i] <= recent_values[i-1]:
                    return False
            return True

        elif direction == 'down':
            # 检查是否连续下降
            for i in range(1, len(recent_values)):
                if recent_values[i] >= recent_values[i-1]:
                    return False
            return True

        else:
            logger.warning(f"Invalid trend direction: {direction}")
            return False


# ========================================================================
# Regime 评估器
# ========================================================================

class RegimeEvaluator(BaseEvaluator):
    """
    Regime 评估器

    支持的运算符：
    - ==: 精确匹配 Regime
    - in: 检查 Regime 是否在列表中
    - transitions: 检查 Regime 变换

    示例：
    {
        "operator": "==",
        "value": "HG"  # High Growth, High Inflation
    }

    {
        "operator": "in",
        "values": ["HG", "LG"]  # 允许增长相关 Regime
    }

    {
        "operator": "transitions",
        "from": "LD",
        "to": "HG"
    }
    """

    def evaluate(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估 Regime 条件

        Args:
            condition: 条件表达式
            context: 上下文数据（必须包含 'regime' 字段）

        Returns:
            是否满足条件
        """
        operator = condition.get('operator')

        if not operator:
            logger.warning(f"Invalid regime condition: {condition}")
            return False

        # 从上下文获取 Regime 数据
        regime_data = context.get('regime', {})
        current_regime_raw = regime_data.get('dominant_regime')
        current_regime = self._normalize_regime(current_regime_raw)

        if current_regime is None:
            logger.warning("Current regime not found in context")
            return False

        try:
            if operator == '==':
                target_value = self._normalize_regime(condition.get('value'))
                return current_regime == target_value

            elif operator == 'in':
                allowed_values = [self._normalize_regime(v) for v in condition.get('values', [])]
                return current_regime in allowed_values

            elif operator == 'transitions':
                return self._evaluate_transitions(condition, regime_data)

            else:
                logger.warning(f"Unsupported operator: {operator}")
                return False

        except Exception as e:
            logger.error(f"Error evaluating regime condition: {e}, condition: {condition}")
            return False

    def _evaluate_transitions(self, condition: dict[str, Any], regime_data: dict[str, Any]) -> bool:
        """
        评估 Regime 变换条件

        Args:
            condition: 条件表达式
            regime_data: Regime 数据

        Returns:
            是否满足变换条件
        """
        from_regime = self._normalize_regime(condition.get('from'))
        to_regime = self._normalize_regime(condition.get('to'))

        previous_regime = self._normalize_regime(regime_data.get('previous_regime'))
        current_regime = self._normalize_regime(regime_data.get('dominant_regime'))

        if previous_regime is None:
            # 没有历史数据，无法判断变换
            return False

        return previous_regime == from_regime and current_regime == to_regime

    @staticmethod
    def _normalize_regime(regime: str | None) -> str | None:
        """统一 Regime 表示：兼容 HG/HD/LG/LD 与英文全称。"""
        if regime is None:
            return None
        mapping = {
            'HG': 'Overheat',
            'HD': 'Recovery',
            'LG': 'Stagflation',
            'LD': 'Deflation',
            'Overheat': 'Overheat',
            'Recovery': 'Recovery',
            'Stagflation': 'Stagflation',
            'Deflation': 'Deflation',
        }
        return mapping.get(regime, regime)


# ========================================================================
# 信号评估器
# ========================================================================

class SignalEvaluator(BaseEvaluator):
    """
    信号评估器

    支持的运算符：
    - AND/OR/NOT: 组合多个信号条件
    - exists: 检查信号是否存在
    - direction: 检查信号方向
    - score: 检查信号评分

    示例：
    {
        "operator": "AND",
        "conditions": [
            {"field": "asset_code", "operator": "==", "value": "ASSET_CODE"},
            {"field": "direction", "operator": "==", "value": "LONG"}
        ]
    }

    {
        "operator": "exists",
        "asset_code": "ASSET_CODE"
    }

    {
        "operator": "score",
        "asset_code": "ASSET_CODE",
        "min_score": 60
    }
    """

    def evaluate(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估信号条件

        Args:
            condition: 条件表达式
            context: 上下文数据（必须包含 'signals' 字段）

        Returns:
            是否满足条件
        """
        operator = condition.get('operator')

        if not operator:
            logger.warning(f"Invalid signal condition: {condition}")
            return False

        # 从上下文获取信号数据
        signals = context.get('signals', [])

        try:
            if operator == 'exists':
                asset_code = condition.get('asset_code')
                return any(s.get('asset_code') == asset_code for s in signals)

            elif operator == 'score':
                return self._evaluate_score(condition, signals)

            elif operator == 'AND':
                return self._evaluate_and(condition, context)

            elif operator == 'OR':
                return self._evaluate_or(condition, context)

            elif operator == 'NOT':
                return self._evaluate_not(condition, context)

            else:
                logger.warning(f"Unsupported operator: {operator}")
                return False

        except Exception as e:
            logger.error(f"Error evaluating signal condition: {e}, condition: {condition}")
            return False

    def _evaluate_score(self, condition: dict[str, Any], signals: list[dict]) -> bool:
        """评估信号评分条件"""
        asset_code = condition.get('asset_code')
        min_score = condition.get('min_score', 0)

        for signal in signals:
            if signal.get('asset_code') == asset_code:
                score = signal.get('total_score', 0)
                return score >= min_score

        return False

    def _evaluate_and(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 AND 条件"""
        sub_conditions = condition.get('conditions', [])
        return all(
            self.evaluate(cond, context)
            for cond in sub_conditions
        )

    def _evaluate_or(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 OR 条件"""
        sub_conditions = condition.get('conditions', [])
        return any(
            self.evaluate(cond, context)
            for cond in sub_conditions
        )

    def _evaluate_not(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 NOT 条件"""
        sub_condition = condition.get('condition')
        if sub_condition:
            return not self.evaluate(sub_condition, context)
        return False


# ========================================================================
# 组合条件评估器
# ========================================================================

class CompositeEvaluator(BaseEvaluator):
    """
    组合条件评估器

    支持 AND/OR/NOT 逻辑组合
    支持嵌套条件

    示例：
    {
        "operator": "AND",
        "conditions": [
            {"type": "macro", "operator": ">", "indicator": "CN_PMI_MANUFACTURING", "threshold": 50},
            {"type": "regime", "operator": "==", "value": "HG"},
            {
                "type": "composite",
                "operator": "OR",
                "conditions": [
                    {"type": "signal", "operator": "exists", "asset_code": "ASSET_CODE_1"},
                    {"type": "signal", "operator": "exists", "asset_code": "ASSET_CODE_2"}
                ]
            }
        ]
    }
    """

    def __init__(self):
        # 初始化子评估器
        self.macro_evaluator = MacroIndicatorEvaluator()
        self.regime_evaluator = RegimeEvaluator()
        self.signal_evaluator = SignalEvaluator()

    def evaluate(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估组合条件

        Args:
            condition: 条件表达式
            context: 上下文数据

        Returns:
            是否满足条件
        """
        operator = condition.get('operator')

        if not operator:
            logger.warning(f"Invalid composite condition: {condition}")
            return False

        try:
            if operator == 'AND':
                return self._evaluate_and(condition, context)

            elif operator == 'OR':
                return self._evaluate_or(condition, context)

            elif operator == 'NOT':
                return self._evaluate_not(condition, context)

            else:
                logger.warning(f"Unsupported composite operator: {operator}")
                return False

        except Exception as e:
            logger.error(f"Error evaluating composite condition: {e}, condition: {condition}")
            return False

    def _evaluate_and(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 AND 条件"""
        sub_conditions = condition.get('conditions', [])

        for sub_cond in sub_conditions:
            if not self._evaluate_sub_condition(sub_cond, context):
                return False

        return True

    def _evaluate_or(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 OR 条件"""
        sub_conditions = condition.get('conditions', [])

        for sub_cond in sub_conditions:
            if self._evaluate_sub_condition(sub_cond, context):
                return True

        return False

    def _evaluate_not(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """评估 NOT 条件"""
        sub_condition = condition.get('condition')

        if sub_condition:
            return not self._evaluate_sub_condition(sub_condition, context)

        return False

    def _evaluate_sub_condition(self, condition: dict[str, Any], context: dict[str, Any]) -> bool:
        """
        评估子条件

        Args:
            condition: 子条件表达式
            context: 上下文数据

        Returns:
            是否满足子条件
        """
        condition_type = condition.get('type', 'composite')

        if condition_type == 'macro':
            return self.macro_evaluator.evaluate(condition, context)

        elif condition_type == 'regime':
            return self.regime_evaluator.evaluate(condition, context)

        elif condition_type == 'signal':
            return self.signal_evaluator.evaluate(condition, context)

        elif condition_type == 'composite':
            return self.evaluate(condition, context)

        else:
            logger.warning(f"Unknown condition type: {condition_type}")
            return False


# ========================================================================
# 组合规则评估器（主入口）
# ========================================================================

class CompositeRuleEvaluator:
    """
    组合规则评估器（主入口）

    根据规则类型分发到对应的评估器

    支持的规则类型：
    - macro: 宏观指标规则
    - regime: Regime 规则
    - signal: 信号规则
    - technical: 技术指标规则（暂不实现）
    - composite: 组合规则
    """

    def __init__(self):
        self.macro_evaluator = MacroIndicatorEvaluator()
        self.regime_evaluator = RegimeEvaluator()
        self.signal_evaluator = SignalEvaluator()
        self.composite_evaluator = CompositeEvaluator()

    def evaluate(
        self,
        rule: RuleCondition,
        context: dict[str, Any]
    ) -> bool:
        """
        评估规则条件

        Args:
            rule: 规则条件实体
            context: 上下文数据（包含 macro, regime, signals, asset_pool 等）

        Returns:
            是否满足条件
        """
        if not rule.is_enabled:
            logger.info(f"Rule is disabled: {rule.rule_name}")
            return False

        condition_json = rule.condition_json

        try:
            if rule.rule_type == RuleType.MACRO:
                return self.macro_evaluator.evaluate(condition_json, context)

            elif rule.rule_type == RuleType.REGIME:
                return self.regime_evaluator.evaluate(condition_json, context)

            elif rule.rule_type == RuleType.SIGNAL:
                return self.signal_evaluator.evaluate(condition_json, context)

            elif rule.rule_type == RuleType.COMPOSITE:
                return self.composite_evaluator.evaluate(condition_json, context)

            elif rule.rule_type == RuleType.TECHNICAL:
                logger.warning("Technical rules are not implemented yet")
                return False

            else:
                logger.warning(f"Unknown rule type: {rule.rule_type}")
                return False

        except Exception as e:
            logger.error(f"Error evaluating rule {rule.rule_name}: {e}")
            return False

    def evaluate_batch(
        self,
        rules: list[RuleCondition],
        context: dict[str, Any]
    ) -> dict[int, bool]:
        """
        批量评估规则

        Args:
            rules: 规则条件列表
            context: 上下文数据

        Returns:
            规则ID到评估结果的映射
        """
        results = {}

        for rule in rules:
            results[rule.rule_id] = self.evaluate(rule, context)

        return results
