"""
规则评估器单元测试

测试覆盖：
- MacroIndicatorEvaluator
- RegimeEvaluator
- SignalEvaluator
- CompositeEvaluator
- CompositeRuleEvaluator
"""
import pytest

from apps.strategy.application.rule_evaluator import (
    CompositeEvaluator,
    CompositeRuleEvaluator,
    MacroIndicatorEvaluator,
    RegimeEvaluator,
    SignalEvaluator,
)
from apps.strategy.domain.entities import ActionType, RuleCondition, RuleType

# ========================================================================
# 宏观指标评估器测试
# ========================================================================

class TestMacroIndicatorEvaluator:
    """宏观指标评估器测试"""

    @pytest.fixture
    def evaluator(self):
        return MacroIndicatorEvaluator()

    @pytest.fixture
    def basic_context(self):
        return {
            'macro': {
                'CN_PMI_MANUFACTURING': 50.5,
                'US_10Y_TREASURY_YIELD': 4.2,
                'CN_CPI_YOY': 2.1
            }
        }

    def test_greater_than_operator(self, evaluator, basic_context):
        """测试大于运算符"""
        condition = {
            'operator': '>',
            'indicator': 'CN_PMI_MANUFACTURING',
            'threshold': 50
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['threshold'] = 51
        assert evaluator.evaluate(condition, basic_context) is False

    def test_less_than_operator(self, evaluator, basic_context):
        """测试小于运算符"""
        condition = {
            'operator': '<',
            'indicator': 'US_10Y_TREASURY_YIELD',
            'threshold': 5.0
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['threshold'] = 4.0
        assert evaluator.evaluate(condition, basic_context) is False

    def test_greater_equal_operator(self, evaluator, basic_context):
        """测试大于等于运算符"""
        condition = {
            'operator': '>=',
            'indicator': 'CN_PMI_MANUFACTURING',
            'threshold': 50.5
        }
        assert evaluator.evaluate(condition, basic_context) is True

    def test_less_equal_operator(self, evaluator, basic_context):
        """测试小于等于运算符"""
        condition = {
            'operator': '<=',
            'indicator': 'CN_CPI_YOY',
            'threshold': 3.0
        }
        assert evaluator.evaluate(condition, basic_context) is True

    def test_equal_operator(self, evaluator, basic_context):
        """测试等于运算符"""
        condition = {
            'operator': '==',
            'indicator': 'CN_PMI_MANUFACTURING',
            'threshold': 50.5
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['threshold'] = 50.6
        assert evaluator.evaluate(condition, basic_context) is False

    def test_not_equal_operator(self, evaluator, basic_context):
        """测试不等于运算符"""
        condition = {
            'operator': '!=',
            'indicator': 'CN_PMI_MANUFACTURING',
            'threshold': 49.0
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['threshold'] = 50.5
        assert evaluator.evaluate(condition, basic_context) is False

    def test_between_operator(self, evaluator, basic_context):
        """测试区间运算符"""
        condition = {
            'operator': 'between',
            'indicator': 'US_10Y_TREASURY_YIELD',
            'min': 4.0,
            'max': 5.0
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['min'] = 4.5
        assert evaluator.evaluate(condition, basic_context) is False

    def test_trend_operator_up(self, evaluator):
        """测试上升趋势判断"""
        context = {
            'macro': {
                'CN_CPI_YOY': 2.5,
                'CN_CPI_YOY_history': [2.0, 2.1, 2.3, 2.5]
            }
        }
        condition = {
            'operator': 'trend',
            'indicator': 'CN_CPI_YOY',
            'direction': 'up',
            'periods': 3
        }
        assert evaluator.evaluate(condition, context) is True

    def test_trend_operator_down(self, evaluator):
        """测试下降趋势判断"""
        context = {
            'macro': {
                'CN_CPI_YOY': 2.0,
                'CN_CPI_YOY_history': [2.5, 2.3, 2.1, 2.0]
            }
        }
        condition = {
            'operator': 'trend',
            'indicator': 'CN_CPI_YOY',
            'direction': 'down',
            'periods': 3
        }
        assert evaluator.evaluate(condition, context) is True

    def test_missing_indicator(self, evaluator, basic_context):
        """测试缺失指标"""
        condition = {
            'operator': '>',
            'indicator': 'NONEXISTENT_INDICATOR',
            'threshold': 50
        }
        assert evaluator.evaluate(condition, basic_context) is False

    def test_invalid_operator(self, evaluator, basic_context):
        """测试无效运算符"""
        condition = {
            'operator': 'invalid_op',
            'indicator': 'CN_PMI_MANUFACTURING',
            'threshold': 50
        }
        assert evaluator.evaluate(condition, basic_context) is False


# ========================================================================
# Regime 评估器测试
# ========================================================================

class TestRegimeEvaluator:
    """Regime 评估器测试"""

    @pytest.fixture
    def evaluator(self):
        return RegimeEvaluator()

    @pytest.fixture
    def basic_context(self):
        return {
            'regime': {
                'dominant_regime': 'HG',
                'confidence': 0.85,
                'growth_momentum_z': 1.5,
                'inflation_momentum_z': 1.2
            }
        }

    def test_equal_operator(self, evaluator, basic_context):
        """测试等于运算符"""
        condition = {
            'operator': '==',
            'value': 'HG'
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['value'] = 'LG'
        assert evaluator.evaluate(condition, basic_context) is False

    def test_in_operator(self, evaluator, basic_context):
        """测试 in 运算符"""
        condition = {
            'operator': 'in',
            'values': ['HG', 'LG']
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['values'] = ['LG', 'LD']
        assert evaluator.evaluate(condition, basic_context) is False

    def test_transitions_operator(self, evaluator):
        """测试 Regime 变换"""
        context = {
            'regime': {
                'dominant_regime': 'HG',
                'previous_regime': 'LD'
            }
        }
        condition = {
            'operator': 'transitions',
            'from': 'LD',
            'to': 'HG'
        }
        assert evaluator.evaluate(condition, context) is True

        condition['from'] = 'LG'
        assert evaluator.evaluate(condition, context) is False

    def test_missing_regime(self, evaluator):
        """测试缺失 Regime 数据"""
        condition = {
            'operator': '==',
            'value': 'HG'
        }
        assert evaluator.evaluate(condition, {}) is False


# ========================================================================
# 信号评估器测试
# ========================================================================

class TestSignalEvaluator:
    """信号评估器测试"""

    @pytest.fixture
    def evaluator(self):
        return SignalEvaluator()

    @pytest.fixture
    def basic_context(self):
        return {
            'signals': [
                {
                    'asset_code': '000001.SH',
                    'asset_name': '上证指数',
                    'direction': 'LONG',
                    'total_score': 75,
                    'regime_score': 80,
                    'policy_score': 70
                },
                {
                    'asset_code': '510300.SH',
                    'asset_name': '沪深300ETF',
                    'direction': 'LONG',
                    'total_score': 68,
                    'regime_score': 72,
                    'policy_score': 65
                }
            ]
        }

    def test_exists_operator(self, evaluator, basic_context):
        """测试 exists 运算符"""
        condition = {
            'operator': 'exists',
            'asset_code': '000001.SH'
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['asset_code'] = '000002.SH'
        assert evaluator.evaluate(condition, basic_context) is False

    def test_score_operator(self, evaluator, basic_context):
        """测试 score 运算符"""
        condition = {
            'operator': 'score',
            'asset_code': '000001.SH',
            'min_score': 70
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['min_score'] = 80
        assert evaluator.evaluate(condition, basic_context) is False

    def test_and_operator(self, evaluator, basic_context):
        """测试 AND 运算符"""
        condition = {
            'operator': 'AND',
            'conditions': [
                {'operator': 'exists', 'asset_code': '000001.SH'},
                {'operator': 'score', 'asset_code': '000001.SH', 'min_score': 70}
            ]
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['conditions'][1]['min_score'] = 80
        assert evaluator.evaluate(condition, basic_context) is False

    def test_or_operator(self, evaluator, basic_context):
        """测试 OR 运算符"""
        condition = {
            'operator': 'OR',
            'conditions': [
                {'operator': 'exists', 'asset_code': '000001.SH'},
                {'operator': 'exists', 'asset_code': '000002.SH'}
            ]
        }
        assert evaluator.evaluate(condition, basic_context) is True

    def test_not_operator(self, evaluator, basic_context):
        """测试 NOT 运算符"""
        condition = {
            'operator': 'NOT',
            'condition': {'operator': 'exists', 'asset_code': '000002.SH'}
        }
        assert evaluator.evaluate(condition, basic_context) is True

        condition['condition']['asset_code'] = '000001.SH'
        assert evaluator.evaluate(condition, basic_context) is False


# ========================================================================
# 组合评估器测试
# ========================================================================

class TestCompositeEvaluator:
    """组合评估器测试"""

    @pytest.fixture
    def evaluator(self):
        return CompositeEvaluator()

    @pytest.fixture
    def full_context(self):
        return {
            'macro': {
                'CN_PMI_MANUFACTURING': 50.5,
                'US_10Y_TREASURY_YIELD': 4.2
            },
            'regime': {
                'dominant_regime': 'HG',
                'confidence': 0.85
            },
            'signals': [
                {
                    'asset_code': '000001.SH',
                    'total_score': 75
                }
            ]
        }

    def test_nested_and_conditions(self, evaluator, full_context):
        """测试嵌套 AND 条件"""
        condition = {
            'operator': 'AND',
            'conditions': [
                {
                    'type': 'macro',
                    'operator': '>',
                    'indicator': 'CN_PMI_MANUFACTURING',
                    'threshold': 50
                },
                {
                    'type': 'regime',
                    'operator': '==',
                    'value': 'HG'
                },
                {
                    'type': 'signal',
                    'operator': 'exists',
                    'asset_code': '000001.SH'
                }
            ]
        }
        assert evaluator.evaluate(condition, full_context) is True

    def test_nested_or_conditions(self, evaluator, full_context):
        """测试嵌套 OR 条件"""
        condition = {
            'operator': 'OR',
            'conditions': [
                {
                    'type': 'macro',
                    'operator': '>',
                    'indicator': 'CN_PMI_MANUFACTURING',
                    'threshold': 55
                },
                {
                    'type': 'regime',
                    'operator': '==',
                    'value': 'HG'
                }
            ]
        }
        assert evaluator.evaluate(condition, full_context) is True

    def test_complex_nested_conditions(self, evaluator, full_context):
        """测试复杂嵌套条件"""
        condition = {
            'operator': 'AND',
            'conditions': [
                {
                    'type': 'regime',
                    'operator': '==',
                    'value': 'HG'
                },
                {
                    'type': 'composite',
                    'operator': 'OR',
                    'conditions': [
                        {
                            'type': 'macro',
                            'operator': '>',
                            'indicator': 'CN_PMI_MANUFACTURING',
                            'threshold': 50
                        },
                        {
                            'type': 'signal',
                            'operator': 'score',
                            'asset_code': '000001.SH',
                            'min_score': 80
                        }
                    ]
                }
            ]
        }
        assert evaluator.evaluate(condition, full_context) is True

    def test_not_condition(self, evaluator, full_context):
        """测试 NOT 条件"""
        condition = {
            'operator': 'NOT',
            'condition': {
                'type': 'regime',
                'operator': '==',
                'value': 'LG'
            }
        }
        assert evaluator.evaluate(condition, full_context) is True


# ========================================================================
# 组合规则评估器测试（主入口）
# ========================================================================

class TestCompositeRuleEvaluator:
    """组合规则评估器测试（主入口）"""

    @pytest.fixture
    def evaluator(self):
        return CompositeRuleEvaluator()

    @pytest.fixture
    def full_context(self):
        return {
            'macro': {
                'CN_PMI_MANUFACTURING': 50.5,
                'US_10Y_TREASURY_YIELD': 4.2
            },
            'regime': {
                'dominant_regime': 'HG',
                'confidence': 0.85
            },
            'signals': [
                {
                    'asset_code': '000001.SH',
                    'total_score': 75
                }
            ],
            'asset_pool': [
                {'asset_code': '000001.SH', 'total_score': 75}
            ]
        }

    def test_evaluate_macro_rule(self, evaluator, full_context):
        """测试评估宏观指标规则"""
        rule = RuleCondition(
            rule_id=1,
            strategy_id=1,
            rule_name="PMI 扩张",
            rule_type=RuleType.MACRO,
            condition_json={
                'operator': '>',
                'indicator': 'CN_PMI_MANUFACTURING',
                'threshold': 50
            },
            action=ActionType.BUY,
            is_enabled=True
        )
        assert evaluator.evaluate(rule, full_context) is True

    def test_evaluate_regime_rule(self, evaluator, full_context):
        """测试评估 Regime 规则"""
        rule = RuleCondition(
            rule_id=2,
            strategy_id=1,
            rule_name="高增长 Regime",
            rule_type=RuleType.REGIME,
            condition_json={
                'operator': '==',
                'value': 'HG'
            },
            action=ActionType.BUY,
            is_enabled=True
        )
        assert evaluator.evaluate(rule, full_context) is True

    def test_evaluate_signal_rule(self, evaluator, full_context):
        """测试评估信号规则"""
        rule = RuleCondition(
            rule_id=3,
            strategy_id=1,
            rule_name="信号存在",
            rule_type=RuleType.SIGNAL,
            condition_json={
                'operator': 'exists',
                'asset_code': '000001.SH'
            },
            action=ActionType.BUY,
            is_enabled=True
        )
        assert evaluator.evaluate(rule, full_context) is True

    def test_evaluate_composite_rule(self, evaluator, full_context):
        """测试评估组合规则"""
        rule = RuleCondition(
            rule_id=4,
            strategy_id=1,
            rule_name="组合条件",
            rule_type=RuleType.COMPOSITE,
            condition_json={
                'operator': 'AND',
                'conditions': [
                    {
                        'type': 'macro',
                        'operator': '>',
                        'indicator': 'CN_PMI_MANUFACTURING',
                        'threshold': 50
                    },
                    {
                        'type': 'regime',
                        'operator': '==',
                        'value': 'HG'
                    }
                ]
            },
            action=ActionType.BUY,
            is_enabled=True
        )
        assert evaluator.evaluate(rule, full_context) is True

    def test_disabled_rule(self, evaluator, full_context):
        """测试禁用的规则"""
        rule = RuleCondition(
            rule_id=5,
            strategy_id=1,
            rule_name="PMI 扩张",
            rule_type=RuleType.MACRO,
            condition_json={
                'operator': '>',
                'indicator': 'CN_PMI_MANUFACTURING',
                'threshold': 50
            },
            action=ActionType.BUY,
            is_enabled=False
        )
        assert evaluator.evaluate(rule, full_context) is False

    def test_batch_evaluate(self, evaluator, full_context):
        """测试批量评估"""
        rules = [
            RuleCondition(
                rule_id=1,
                strategy_id=1,
                rule_name="PMI 扩张",
                rule_type=RuleType.MACRO,
                condition_json={
                    'operator': '>',
                    'indicator': 'CN_PMI_MANUFACTURING',
                    'threshold': 50
                },
                action=ActionType.BUY,
                is_enabled=True
            ),
            RuleCondition(
                rule_id=2,
                strategy_id=1,
                rule_name="高增长 Regime",
                rule_type=RuleType.REGIME,
                condition_json={
                    'operator': '==',
                    'value': 'LG'  # 不满足
                },
                action=ActionType.BUY,
                is_enabled=True
            )
        ]

        results = evaluator.evaluate_batch(rules, full_context)
        assert results[1] is True
        assert results[2] is False
