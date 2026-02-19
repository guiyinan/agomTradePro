"""
Unit tests for Invalidation Domain Layer.

Pure Domain layer tests using only Python standard library.
"""

import pytest
from datetime import date

from apps.signal.domain.invalidation import (
    InvalidationRule,
    InvalidationCondition,
    InvalidationCheckResult,
    IndicatorValue,
    ComparisonOperator,
    LogicOperator,
    IndicatorType,
    evaluate_rule,
    evaluate_condition,
    _compare,
    validate_rule,
)
from apps.signal.domain.parser import (
    InvalidationLogicParser,
    ParseResult,
    validate_parse_input,
)
from apps.signal.domain.indicators import (
    IndicatorDefinition,
    IndicatorCategory,
    get_indicator,
    find_indicator_by_alias,
    get_all_indicators,
    get_indicators_by_category,
)


# ==================== Test ComparisonOperator ====================

class TestComparisonOperator:
    """测试比较操作符"""

    def test_lt_operator(self):
        assert _compare(40, ComparisonOperator.LT, 50) is True
        assert _compare(50, ComparisonOperator.LT, 50) is False
        assert _compare(60, ComparisonOperator.LT, 50) is False

    def test_lte_operator(self):
        assert _compare(40, ComparisonOperator.LTE, 50) is True
        assert _compare(50, ComparisonOperator.LTE, 50) is True
        assert _compare(60, ComparisonOperator.LTE, 50) is False

    def test_gt_operator(self):
        assert _compare(60, ComparisonOperator.GT, 50) is True
        assert _compare(50, ComparisonOperator.GT, 50) is False
        assert _compare(40, ComparisonOperator.GT, 50) is False

    def test_gte_operator(self):
        assert _compare(60, ComparisonOperator.GTE, 50) is True
        assert _compare(50, ComparisonOperator.GTE, 50) is True
        assert _compare(40, ComparisonOperator.GTE, 50) is False

    def test_eq_operator(self):
        assert _compare(50, ComparisonOperator.EQ, 50) is True
        assert _compare(50.001, ComparisonOperator.EQ, 50) is True  # 容差
        assert _compare(50.1, ComparisonOperator.EQ, 50) is False


# ==================== Test InvalidationCondition ====================

class TestInvalidationCondition:
    """测试证伪条件"""

    def test_create_condition(self):
        """测试创建条件"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        assert cond.indicator_code == "CN_PMI_MANUFACTURING"
        assert cond.indicator_type == IndicatorType.MACRO
        assert cond.operator == ComparisonOperator.LT
        assert cond.threshold == 50.0
        assert cond.duration is None
        assert cond.compare_with is None

    def test_condition_with_duration(self):
        """测试带持续时间的条件"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
            duration=2,
        )
        assert cond.duration == 2

    def test_condition_with_compare_with(self):
        """测试带比较对象的条件"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
            compare_with="prev_value",
        )
        assert cond.compare_with == "prev_value"

    def test_condition_validation_invalid_duration(self):
        """测试条件验证：无效的持续时间"""
        with pytest.raises(ValueError, match="duration 必须大于 0"):
            InvalidationCondition(
                indicator_code="TEST",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=50.0,
                duration=0,
            )

    def test_condition_validation_invalid_compare_with(self):
        """测试条件验证：无效的比较对象"""
        with pytest.raises(ValueError, match="不支持的 compare_with"):
            InvalidationCondition(
                indicator_code="TEST",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=50.0,
                compare_with="invalid_value",
            )

    def test_condition_to_dict(self):
        """测试条件转换为字典"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
            duration=2,
        )
        d = cond.to_dict()
        assert d["indicator_code"] == "CN_PMI_MANUFACTURING"
        assert d["indicator_type"] == "macro"
        assert d["operator"] == "lt"
        assert d["threshold"] == 50.0
        assert d["duration"] == 2

    def test_condition_from_dict(self):
        """测试从字典创建条件"""
        d = {
            "indicator_code": "CN_PMI_MANUFACTURING",
            "indicator_type": "macro",
            "operator": "lt",
            "threshold": 50.0,
            "duration": 2,
        }
        cond = InvalidationCondition.from_dict(d)
        assert cond.indicator_code == "CN_PMI_MANUFACTURING"
        assert cond.indicator_type == IndicatorType.MACRO
        assert cond.operator == ComparisonOperator.LT
        assert cond.threshold == 50.0
        assert cond.duration == 2


# ==================== Test InvalidationRule ====================

class TestInvalidationRule:
    """测试证伪规则"""

    def test_create_rule(self):
        """测试创建规则"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(
            conditions=[cond],
            logic=LogicOperator.AND,
        )
        assert len(rule.conditions) == 1
        assert rule.logic == LogicOperator.AND

    def test_rule_validation_empty_conditions(self):
        """测试规则验证：空条件列表"""
        with pytest.raises(ValueError, match="conditions 不能为空"):
            InvalidationRule(
                conditions=[],
                logic=LogicOperator.AND,
            )

    def test_rule_to_dict(self):
        """测试规则转换为字典"""
        cond = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(
            conditions=[cond],
            logic=LogicOperator.AND,
        )
        d = rule.to_dict()
        assert "conditions" in d
        assert len(d["conditions"]) == 1
        assert d["logic"] == "AND"

    def test_rule_from_dict(self):
        """测试从字典创建规则"""
        d = {
            "conditions": [
                {
                    "indicator_code": "CN_PMI_MANUFACTURING",
                    "indicator_type": "macro",
                    "operator": "lt",
                    "threshold": 50.0,
                }
            ],
            "logic": "AND",
        }
        rule = InvalidationRule.from_dict(d)
        assert len(rule.conditions) == 1
        assert rule.logic == LogicOperator.AND

    def test_rule_human_readable(self):
        """测试规则的人类可读描述"""
        cond1 = InvalidationCondition(
            indicator_code="CN_PMI_MANUFACTURING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        cond2 = InvalidationCondition(
            indicator_code="CN_CPI_YOY",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.GT,
            threshold=3.0,
        )
        rule = InvalidationRule(
            conditions=[cond1, cond2],
            logic=LogicOperator.AND,
        )
        hr = rule.human_readable
        assert "CN_PMI_MANUFACTURING" in hr
        assert "<" in hr
        assert "50.0" in hr
        assert "CN_CPI_YOY" in hr
        assert ">" in hr
        assert "3.0" in hr


# ==================== Test evaluate_condition ====================

class TestEvaluateCondition:
    """测试条件评估"""

    def test_evaluate_condition_met(self):
        """测试条件满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        value = IndicatorValue(
            code="PMI",
            current_value=49.0,
            history_values=[50, 51, 52],
            unit="",
            last_updated=None,
        )
        is_met, detail = evaluate_condition(cond, value)
        assert is_met is True
        assert detail["is_met"] is True
        assert detail["actual_value"] == 49.0

    def test_evaluate_condition_not_met(self):
        """测试条件不满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        value = IndicatorValue(
            code="PMI",
            current_value=51.0,
            history_values=[],
            unit="",
            last_updated=None,
        )
        is_met, detail = evaluate_condition(cond, value)
        assert is_met is False
        assert detail["is_met"] is False

    def test_evaluate_condition_no_current_value(self):
        """测试无当前值"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        value = IndicatorValue(
            code="PMI",
            current_value=None,
            history_values=[],
            unit="",
            last_updated=None,
        )
        is_met, detail = evaluate_condition(cond, value)
        assert is_met is False
        assert "error" in detail

    def test_evaluate_condition_with_duration_met(self):
        """测试持续时间条件满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
            duration=2,
        )
        value = IndicatorValue(
            code="PMI",
            current_value=49.0,
            history_values=[49.5, 48],  # 连续2期都满足
            unit="",
            last_updated=None,
        )
        is_met, detail = evaluate_condition(cond, value)
        assert is_met is True

    def test_evaluate_condition_with_duration_not_met(self):
        """测试持续时间条件不满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
            duration=2,
        )
        value = IndicatorValue(
            code="PMI",
            current_value=49.0,
            history_values=[51, 52],  # 只有当前满足，历史不满足
            unit="",
            last_updated=None,
        )
        is_met, detail = evaluate_condition(cond, value)
        assert is_met is False


# ==================== Test evaluate_rule ====================

class TestEvaluateRule:
    """测试规则评估"""

    def test_simple_and_rule_met(self):
        """测试简单 AND 规则满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(conditions=[cond], logic=LogicOperator.AND)

        indicator_values = {
            "PMI": IndicatorValue(
                code="PMI",
                current_value=49.0,
                history_values=[50, 51, 52],
                unit="",
                last_updated=None,
            )
        }

        result = evaluate_rule(rule, indicator_values)
        assert result.is_invalidated is True
        assert "PMI" in result.reason

    def test_simple_and_rule_not_met(self):
        """测试简单 AND 规则不满足"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(conditions=[cond], logic=LogicOperator.AND)

        indicator_values = {
            "PMI": IndicatorValue(
                code="PMI",
                current_value=51.0,
                history_values=[],
                unit="",
                last_updated=None,
            )
        }

        result = evaluate_rule(rule, indicator_values)
        assert result.is_invalidated is False
        assert "未满足" in result.reason

    def test_or_rule_met(self):
        """测试 OR 规则满足"""
        cond1 = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        cond2 = InvalidationCondition(
            indicator_code="CPI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.GT,
            threshold=3.0,
        )
        rule = InvalidationRule(conditions=[cond1, cond2], logic=LogicOperator.OR)

        indicator_values = {
            "PMI": IndicatorValue(code="PMI", current_value=51.0, history_values=[], unit="", last_updated=None),
            "CPI": IndicatorValue(code="CPI", current_value=3.5, history_values=[], unit="", last_updated=None),
        }

        result = evaluate_rule(rule, indicator_values)
        assert result.is_invalidated is True

    def test_or_rule_not_met(self):
        """测试 OR 规则不满足"""
        cond1 = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        cond2 = InvalidationCondition(
            indicator_code="CPI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.GT,
            threshold=3.0,
        )
        rule = InvalidationRule(conditions=[cond1, cond2], logic=LogicOperator.OR)

        indicator_values = {
            "PMI": IndicatorValue(code="PMI", current_value=51.0, history_values=[], unit="", last_updated=None),
            "CPI": IndicatorValue(code="CPI", current_value=2.5, history_values=[], unit="", last_updated=None),
        }

        result = evaluate_rule(rule, indicator_values)
        assert result.is_invalidated is False

    def test_rule_with_missing_indicator(self):
        """测试规则包含缺失的指标"""
        cond = InvalidationCondition(
            indicator_code="MISSING",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(conditions=[cond], logic=LogicOperator.AND)

        indicator_values = {}

        result = evaluate_rule(rule, indicator_values)
        assert result.is_invalidated is False
        assert any("数据不可用" in str(d) for d in result.checked_conditions)


# ==================== Test validate_rule ====================

class TestValidateRule:
    """测试规则验证"""

    def test_validate_valid_rule(self):
        """测试验证有效规则"""
        cond = InvalidationCondition(
            indicator_code="PMI",
            indicator_type=IndicatorType.MACRO,
            operator=ComparisonOperator.LT,
            threshold=50.0,
        )
        rule = InvalidationRule(conditions=[cond], logic=LogicOperator.AND)
        errors = validate_rule(rule)
        assert len(errors) == 0

    def test_validate_empty_conditions(self):
        """测试验证空条件"""
        with pytest.raises(ValueError, match="conditions 不能为空"):
            InvalidationRule(conditions=[], logic=LogicOperator.AND)

    def test_validate_invalid_duration(self):
        """测试验证无效持续时间"""
        with pytest.raises(ValueError, match="duration"):
            InvalidationCondition(
                indicator_code="PMI",
                indicator_type=IndicatorType.MACRO,
                operator=ComparisonOperator.LT,
                threshold=50.0,
                duration=0,  # 无效
            )


# ==================== Test InvalidationLogicParser ====================

class TestInvalidationLogicParser:
    """测试证伪逻辑解析器"""

    def test_parse_simple_condition(self):
        """测试解析简单条件"""
        parser = InvalidationLogicParser()
        result = parser.parse("PMI 跌破 50")

        assert result.success is True
        assert result.rule is not None
        assert len(result.rule.conditions) == 1
        assert result.rule.conditions[0].indicator_code == "CN_PMI_MANUFACTURING"
        assert result.rule.conditions[0].operator == ComparisonOperator.LT
        assert result.rule.conditions[0].threshold == 50.0

    def test_parse_and_conditions(self):
        """测试解析 AND 条件"""
        parser = InvalidationLogicParser()
        result = parser.parse("PMI 跌破 50 且 CPI 大于 3")

        assert result.success is True
        assert len(result.rule.conditions) == 2
        assert result.rule.logic == LogicOperator.AND

    def test_parse_or_conditions(self):
        """测试解析 OR 条件"""
        parser = InvalidationLogicParser()
        result = parser.parse("PMI 跌破 50 或 CPI 大于 3")

        assert result.success is True
        assert result.rule.logic == LogicOperator.OR

    def test_parse_duration(self):
        """测试解析持续时间"""
        parser = InvalidationLogicParser()
        result = parser.parse("PMI 连续2期跌破 50")

        assert result.success is True
        assert result.rule.conditions[0].duration == 2

    def test_parse_empty_input(self):
        """测试解析空输入"""
        parser = InvalidationLogicParser()
        result = parser.parse("")

        assert result.success is False
        assert "不能为空" in result.error

    def test_parse_unknown_indicator(self):
        """测试解析未知指标"""
        parser = InvalidationLogicParser()
        result = parser.parse("UNKNOWN 指标 跌破 50")

        assert result.success is False
        assert "无法识别指标" in result.error

    def test_parse_no_threshold(self):
        """测试解析无阈值"""
        parser = InvalidationLogicParser()
        result = parser.parse("PMI 跌破")

        assert result.success is False
        assert "阈值" in result.error


# ==================== Test Indicator Registry ====================

class TestIndicatorRegistry:
    """测试指标注册表"""

    def test_get_indicator(self):
        """测试获取指标"""
        ind = get_indicator("CN_PMI_MANUFACTURING")
        assert ind is not None
        assert ind.code == "CN_PMI_MANUFACTURING"
        assert ind.name == "制造业PMI"
        assert ind.category == IndicatorCategory.GROWTH

    def test_get_indicator_not_found(self):
        """测试获取不存在的指标"""
        ind = get_indicator("NON_EXISTENT")
        assert ind is None

    def test_find_indicator_by_alias(self):
        """测试通过别名查找指标"""
        ind = find_indicator_by_alias("pmi")
        assert ind is not None
        assert ind.code == "CN_PMI_MANUFACTURING"

        ind = find_indicator_by_alias("制造业pmi")
        assert ind is not None
        assert ind.code == "CN_PMI_MANUFACTURING"

    def test_find_indicator_by_code(self):
        """测试通过代码查找指标"""
        ind = find_indicator_by_alias("CN_PMI_MANUFACTURING")
        assert ind is not None

    def test_get_all_indicators(self):
        """测试获取所有指标"""
        all_ind = get_all_indicators()
        assert len(all_ind) > 0
        assert any(ind.code == "CN_PMI_MANUFACTURING" for ind in all_ind)

    def test_get_indicators_by_category(self):
        """测试按类别获取指标"""
        growth_ind = get_indicators_by_category(IndicatorCategory.GROWTH)
        assert len(growth_ind) > 0
        assert all(ind.category == IndicatorCategory.GROWTH for ind in growth_ind)


# ==================== Test validate_parse_input ====================

class TestValidateParseInput:
    """测试解析输入验证"""

    def test_validate_empty_input(self):
        """测试验证空输入"""
        errors = validate_parse_input("")
        assert len(errors) > 0
        assert any("不能为空" in e for e in errors)

    def test_validate_no_indicator(self):
        """测试验证无指标"""
        errors = validate_parse_input("跌破 50")
        assert len(errors) > 0
        assert any("指标" in e for e in errors)

    def test_validate_no_number(self):
        """测试验证无数字"""
        errors = validate_parse_input("PMI 跌破")
        assert len(errors) > 0
        assert any("阈值" in e for e in errors)

    def test_validate_valid_input(self):
        """测试验证有效输入"""
        errors = validate_parse_input("PMI 跌破 50")
        assert len(errors) == 0
