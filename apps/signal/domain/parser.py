"""
证伪逻辑解析器

将自然语言转换为结构化的 InvalidationRule。

这是 Domain 层的解析器，只使用 Python 标准库。
处理用户输入的自然语言，提取指标、操作符、阈值等信息。
"""

import re
from typing import Dict, List, Optional

from .invalidation import (
    InvalidationRule,
    InvalidationCondition,
    ComparisonOperator,
    LogicOperator,
    IndicatorType,
)
from .indicators import find_indicator_by_alias


class ParseResult:
    """解析结果

    包含解析状态、结果或错误信息。
    """

    def __init__(
        self,
        success: bool,
        rule: Optional[InvalidationRule] = None,
        condition: Optional[InvalidationCondition] = None,
        error: Optional[str] = None,
        warnings: Optional[List[str]] = None,
    ):
        self.success = success
        self.rule = rule
        self.condition = condition
        self.error = error
        self.warnings = warnings or []


class InvalidationLogicParser:
    """证伪逻辑解析器

    将自然语言描述转换为结构化的 InvalidationRule。

    支持的输入示例：
    - "PMI 跌破 50"
    - "CPI > 3"
    - "PMI 跌破 50 且 CPI 大于 3"
    - "PMI 连续2期跌破 50"
    """

    # 比较关键词映射
    COMPARISON_KEYWORDS = {
        ComparisonOperator.LT: ["低于", "跌破", "下破", "小于", "少于", "<", "lt"],
        ComparisonOperator.LTE: ["低于等于", "不超过", "≤", "lte", "<="],
        ComparisonOperator.GT: ["高于", "突破", "上破", "超过", "大于", "多于", ">", "gt"],
        ComparisonOperator.GTE: ["高于等于", "至少", "≥", "gte", ">="],
        ComparisonOperator.EQ: ["等于", "是", "为", "=", "eq", "=="],
    }

    # 持续时间模式
    DURATION_PATTERNS = [
        r"连续(\d+)期",
        r"连续(\d+)个月",
        r"(\d+)期连续",
        r"(\d+)个月连续",
    ]

    # 逻辑分隔符
    OR_SEPARATORS = [" 或 ", " 或者 ", " either ", " or "]
    AND_SEPARATORS = [" 且 ", " 并 ", " 同时 ", " and ", "和", ","]

    def parse(self, user_input: str) -> ParseResult:
        """解析用户输入

        Args:
            user_input: 自然语言描述，如 "PMI 跌破 50" 或 "CPI > 3 且 M2 < 10"

        Returns:
            ParseResult: 包含解析后的规则或错误信息
        """
        if not user_input or not user_input.strip():
            return ParseResult(success=False, error="输入不能为空")

        user_input = user_input.strip()
        warnings = []

        # 1. 检测逻辑操作符
        logic = self._detect_logic(user_input)

        # 2. 分割条件
        condition_texts = self._split_conditions(user_input, logic)

        # 3. 解析每个条件
        conditions = []
        for text in condition_texts:
            result = self._parse_single_condition(text)
            if result.error:
                return ParseResult(success=False, error=result.error)
            if result.condition:
                conditions.append(result.condition)
            warnings.extend(result.warnings or [])

        if not conditions:
            return ParseResult(
                success=False,
                error="无法解析任何条件，请明确指定指标和阈值"
            )

        # 4. 构建规则
        try:
            rule = InvalidationRule(
                conditions=conditions,
                logic=logic
            )
            return ParseResult(success=True, rule=rule, warnings=warnings)
        except ValueError as e:
            return ParseResult(success=False, error=str(e))

    def _detect_logic(self, text: str) -> LogicOperator:
        """检测逻辑操作符

        Args:
            text: 输入文本

        Returns:
            LogicOperator: AND 或 OR
        """
        text_lower = text.lower()
        for sep in self.OR_SEPARATORS:
            if sep in text_lower:
                return LogicOperator.OR
        return LogicOperator.AND

    def _split_conditions(self, text: str, logic: LogicOperator) -> List[str]:
        """分割多个条件

        Args:
            text: 输入文本
            logic: 逻辑操作符

        Returns:
            List[str]: 分割后的条件列表
        """
        separators = self.OR_SEPARATORS if logic == LogicOperator.OR else self.AND_SEPARATORS

        conditions = [text]
        for sep in separators:
            new_conditions = []
            for cond in conditions:
                # 使用分隔符分割
                parts = cond.split(sep)
                new_conditions.extend(parts)
            conditions = new_conditions

        return [c.strip() for c in conditions if c.strip()]

    def _parse_single_condition(self, text: str) -> ParseResult:
        """解析单个条件

        Args:
            text: 条件文本

        Returns:
            ParseResult: 包含解析后的条件或错误信息
        """
        warnings = []

        # 1. 提取指标
        indicator = find_indicator_by_alias(text)
        if not indicator:
            # 尝试提供更友好的错误提示
            available = [ind.name for ind in find_indicators_in_text(text)]
            if available:
                return ParseResult(
                    success=False,
                    error=f"无法识别指标，您是否指的是：{', '.join(available)}？"
                )
            return ParseResult(
                success=False,
                error=f"无法识别指标: {text}。请使用明确的指标名称，如 PMI、CPI、M2 等"
            )

        # 2. 提取操作符
        op = self._extract_operator(text)
        if not op:
            op = ComparisonOperator.LT  # 默认小于
            warnings.append(f"未检测到比较操作符，默认使用 '<'")

        # 3. 提取阈值
        threshold = self._extract_threshold(text)
        if threshold is None:
            threshold = indicator.suggested_threshold
        if threshold is None:
            return ParseResult(
                success=False,
                error=f"无法提取阈值: {text}。请明确指定阈值，如 'PMI 跌破 50'"
            )

        # 4. 提取持续时间
        duration = self._extract_duration(text)

        # 5. 构建条件
        try:
            condition = InvalidationCondition(
                indicator_code=indicator.code,
                indicator_type=IndicatorType.MACRO
                if indicator.category.value in ("growth", "inflation", "interest")
                else IndicatorType.MARKET,
                operator=op,
                threshold=threshold,
                duration=duration,
            )
            return ParseResult(success=True, condition=condition, warnings=warnings)
        except ValueError as e:
            return ParseResult(success=False, error=str(e))

    def _extract_operator(self, text: str) -> Optional[ComparisonOperator]:
        """提取比较操作符

        Args:
            text: 输入文本

        Returns:
            ComparisonOperator 或 None
        """
        for op, keywords in self.COMPARISON_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return op
        return None

    def _extract_threshold(self, text: str) -> Optional[float]:
        """提取阈值

        支持多种格式：
        - "PMI < 50"
        - "跌破 50"
        - "大于 3.5"

        Args:
            text: 输入文本

        Returns:
            float 或 None
        """
        patterns = [
            r'[<>]=?\s*([+-]?\d+\.?\d*)',  # >= 50, < 3
            r'(?:跌破|突破|超过|低于|高于)(?:到)?\s*([+-]?\d+\.?\d*)',  # 跌破50
            r'(?:小于|大于|等于)\s*([+-]?\d+\.?\d*)',  # 小于50
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    continue
        return None

    def _extract_duration(self, text: str) -> Optional[int]:
        """提取持续时间

        支持格式：
        - "连续2期"
        - "连续3个月"

        Args:
            text: 输入文本

        Returns:
            int 或 None
        """
        for pattern in self.DURATION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue
        return None


def find_indicators_in_text(text: str) -> List:
    """在文本中查找可能的指标

    用于提供错误提示和建议。

    Args:
        text: 输入文本

    Returns:
        List[IndicatorDefinition]: 可能的指标列表
    """
    from .indicators import get_all_indicators

    text_lower = text.lower()
    found = []

    for indicator in get_all_indicators():
        # 检查别名是否在文本中
        alias_found = False
        for alias in indicator.aliases:
            if alias.lower() in text_lower:
                found.append(indicator)
                alias_found = True
                break
        # 检查名称是否在文本中
        if not alias_found and indicator.name.lower() in text_lower:
            found.append(indicator)

    return found


def validate_parse_input(user_input: str) -> List[str]:
    """验证解析输入的有效性

    在解析前进行基本验证，提供友好的错误提示。

    Args:
        user_input: 用户输入

    Returns:
        List[str]: 错误列表，空列表表示通过验证
    """
    errors = []

    if not user_input or not user_input.strip():
        errors.append("输入不能为空")
        return errors

    # 检查是否包含指标
    indicators = find_indicators_in_text(user_input)
    if not indicators:
        errors.append("未检测到有效的指标名称，请使用 PMI、CPI、M2 等标准指标名称")

    # 检查是否包含数字
    if not re.search(r'\d+\.?\d*', user_input):
        errors.append("未检测到阈值，请指定具体的数值，如 'PMI 跌破 50'")

    return errors
