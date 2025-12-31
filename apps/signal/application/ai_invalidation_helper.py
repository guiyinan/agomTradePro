"""
AI 证伪条件助手

使用 AI 帮助用户生成结构化的证伪条件
"""

import re
import json
from typing import Dict, List, Optional, Tuple
from apps.macro.application.indicator_service import IndicatorService


class AIInvalidationHelper:
    """AI 证伪条件助手"""

    # 指标别名映射
    INDICATOR_ALIASES = {
        # PMI 变体
        'pmi': 'CN_PMI_MANUFACTURING',
        '制造业pmi': 'CN_PMI_MANUFACTURING',
        '采购经理指数': 'CN_PMI_MANUFACTURING',
        '非制造业pmi': 'CN_PMI_NON_MANUFACTURING',

        # CPI 变体
        'cpi': 'CN_CPI_YOY',
        '消费者物价指数': 'CN_CPI_YOY',
        '物价': 'CN_CPI_YOY',
        '通胀': 'CN_CPI_YOY',
        'cpi同比': 'CN_CPI_YOY',
        'cpi环比': 'CN_CPI_MOY',

        # PPI 变体
        'ppi': 'CN_PPI_YOY',
        '生产者物价指数': 'CN_PPI_YOY',
        '出厂价格': 'CN_PPI_YOY',

        # M2 变体
        'm2': 'CN_M2_YOY',
        '货币供应量': 'CN_M2_YOY',
        '广义货币': 'CN_M2_YOY',
        'm2同比': 'CN_M2_YOY',

        # 利率变体
        'shibor': 'SHIBOR_1M',
        'shibor隔夜': 'SHIBOR_O_N',
        'shibor1月': 'SHIBOR_1M',
        '银行间利率': 'SHIBOR_1M',
        '拆借利率': 'SHIBOR_1M',
        'lpr': 'CN_LPR_1Y',
        'lpr1年': 'CN_LPR_1Y',
        '贷款利率': 'CN_LPR_1Y',
        '市场利率': 'SHIBOR_1M',

        # GDP 变体
        'gdp': 'CN_GDP_YOY',
        '国内生产总值': 'CN_GDP_YOY',
        '经济增速': 'CN_GDP_YOY',

        # 汇率变体
        '美元人民币': 'USDCNY',
        'usdcny': 'USDCNY',
        '人民币汇率': 'USDCNY',
        '汇率': 'USDCNY',

        # 股票变体
        '上证': '000001.SH',
        '上证指数': '000001.SH',
        '大盘': '000001.SH',
        '沪深': '000001.SH',
        '深证': '399001.SZ',
        '深证成指': '399001.SZ',
        '创业板': '399006.SZ',
    }

    # 条件关键词映射
    CONDITION_KEYWORDS = {
        # 小于
        'lt': ['低于', '跌破', '下破', '小于', '少于', '<', 'lt'],
        # 小于等于
        'lte': ['低于等于', '不超过', '≤', 'lte'],
        # 大于
        'gt': ['高于', '突破', '上破', '超过', '大于', '多于', '>', 'gt'],
        # 大于等于
        'gte': ['高于等于', '至少', '≥', 'gte'],
        # 等于
        'eq': ['等于', '是', '为', '=', 'eq'],
    }

    # 连续关键词
    DURATION_KEYWORDS = [
        r'连续(\d+)期',
        r'连续(\d+)个月',
        r'(\d+)期连续',
        r'(\d+)个月连续',
    ]

    def __init__(self):
        self.indicators = IndicatorService.get_available_indicators()
        self.indicator_map = {ind['code']: ind for ind in self.indicators}

    def parse_invalidation_logic(self, user_input: str) -> Dict:
        """
        解析用户输入的证伪逻辑，生成结构化条件

        Args:
            user_input: 用户输入的自然语言描述

        Returns:
            Dict: {
                'conditions': [...],
                'logic': 'AND/OR',
                'explanation': '...',
                'confidence': 0.95
            }
        """
        user_input = user_input.lower().strip()

        # 解析逻辑关系（AND/OR）
        logic = self._detect_logic(user_input)

        # 分割多个条件
        condition_texts = self._split_conditions(user_input, logic)

        # 解析每个条件
        conditions = []
        for text in condition_texts:
            condition = self._parse_single_condition(text)
            if condition:
                conditions.append(condition)

        if not conditions:
            return {
                'error': '无法解析证伪条件，请明确指定指标和阈值',
                'suggestions': self._generate_suggestions(user_input)
            }

        # 生成解释
        explanation = self._generate_explanation(conditions, logic)

        return {
            'conditions': conditions,
            'logic': logic,
            'explanation': explanation,
            'confidence': self._calculate_confidence(conditions, user_input)
        }

    def _detect_logic(self, text: str) -> str:
        """检测逻辑关系"""
        # 检查 OR 关键词
        or_keywords = ['或', '或者', 'either', 'or', '且不', '不同时']
        for kw in or_keywords:
            if kw in text:
                return 'OR'
        return 'AND'

    def _split_conditions(self, text: str, logic: str) -> List[str]:
        """分割多个条件"""
        if logic == 'OR':
            separators = [' 或 ', ' 或者 ', ' either ', ' or ']
        else:
            separators = [' 且 ', ' 并 ', ' 同时 ', ' and ', '和', ',']

        conditions = [text]
        for sep in separators:
            new_conditions = []
            for cond in conditions:
                new_conditions.extend(cond.split(sep))
            conditions = new_conditions

        return [c.strip() for c in conditions if c.strip()]

    def _parse_single_condition(self, text: str) -> Optional[Dict]:
        """解析单个条件"""
        # 1. 提取指标
        indicator_code = self._extract_indicator(text)
        if not indicator_code:
            return None

        # 2. 提取条件操作符
        condition_op = self._extract_condition_op(text)
        if not condition_op:
            condition_op = 'lt'  # 默认小于

        # 3. 提取阈值
        threshold = self._extract_threshold(text, indicator_code)
        if threshold is None:
            # 尝试从指标元数据获取推荐阈值
            ind_data = self.indicator_map.get(indicator_code, {})
            threshold = ind_data.get('suggested_threshold')

        if threshold is None:
            return None

        # 4. 提取持续时间（可选）
        duration = self._extract_duration(text)

        condition = {
            'indicator': indicator_code,
            'condition': condition_op,
            'threshold': threshold,
        }

        if duration:
            condition['duration'] = duration

        return condition

    def _extract_indicator(self, text: str) -> Optional[str]:
        """提取指标代码"""
        # 先检查别名
        for alias, code in self.INDICATOR_ALIASES.items():
            if alias in text:
                return code

        # 检查完整指标名称
        for ind in self.indicators:
            if ind['code'].lower() in text or ind['name'] in text:
                return ind['code']

        return None

    def _extract_condition_op(self, text: str) -> Optional[str]:
        """提取条件操作符"""
        for op, keywords in self.CONDITION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return op
        return None

    def _extract_threshold(self, text: str, indicator_code: str) -> Optional[float]:
        """提取阈值"""
        # 尝试直接提取数字
        # 匹配: 跌破50, > 3%, 小于2.5, etc.
        patterns = [
            r'[<>]=?\s*([+-]?\d+\.?\d*)',  # >= 50, < 3
            r'(?:跌破|突破|超过|低于|高于)(?:到)?\s*([+-]?\d+\.?\d*)',  # 跌破50
            r'(?:小于|大于|等于)\s*([+-]?\d+\.?\d*)',  # 小于50
            r'[<>]\s*([+-]?\d+\.?\d*)',  # < 50
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return float(match.group(1))
                except:
                    continue

        return None

    def _extract_duration(self, text: str) -> Optional[int]:
        """提取持续时间"""
        for pattern in self.DURATION_KEYWORDS:
            match = re.search(pattern, text)
            if match:
                try:
                    return int(match.group(1))
                except:
                    continue
        return None

    def _generate_explanation(self, conditions: List[Dict], logic: str) -> str:
        """生成人类可读的解释"""
        op_map = {'lt': '<', 'lte': '≤', 'gt': '>', 'gte': '≥', 'eq': '='}

        condition_texts = []
        for cond in conditions:
            ind_code = cond['indicator']
            ind_data = self.indicator_map.get(ind_code, {})
            ind_name = ind_data.get('name', ind_code)

            text = f"{ind_name} {op_map[cond['condition']]} {cond['threshold']}"
            if cond.get('duration'):
                text += f" 连续{cond['duration']}期"
            condition_texts.append(text)

        logic_text = ' 且 ' if logic == 'AND' else ' 或 '
        return f"当{' 且 '.join(condition_texts)}时，信号将被证伪"

    def _calculate_confidence(self, conditions: List[Dict], original_text: str) -> float:
        """计算解析置信度"""
        score = 1.0

        # 检查是否包含明确的指标名称
        has_indicator = any(c['indicator'] in original_text or
                           self.indicator_map.get(c['indicator'], {}).get('name', '') in original_text
                           for c in conditions)
        if not has_indicator:
            score -= 0.2

        # 检查是否包含明确的操作符
        has_operator = any(kw in original_text
                          for keywords in self.CONDITION_KEYWORDS.values()
                          for kw in keywords)
        if has_operator:
            score += 0.1

        # 检查是否包含数字
        has_number = bool(re.search(r'\d+\.?\d*', original_text))
        if has_number:
            score += 0.1

        return max(0.5, min(1.0, score))

    def _generate_suggestions(self, user_input: str) -> List[str]:
        """生成改进建议"""
        suggestions = []

        # 检查是否提到了指标
        has_indicator = any(alias in user_input for alias in self.INDICATOR_ALIASES.keys())
        if not has_indicator:
            available = ', '.join(list(self.INDICATOR_ALIASES.keys())[:10])
            suggestions.append(f"请明确指定指标，如: PMI、CPI、M2、SHIBOR等")

        # 检查是否提到了阈值
        has_number = bool(re.search(r'\d+\.?\d*', user_input))
        if not has_number:
            suggestions.append("请指定阈值，如: 跌破50、大于3%")

        # 检查是否提到了条件
        has_condition = any(kw in user_input
                           for keywords in self.CONDITION_KEYWORDS.values()
                           for kw in keywords)
        if not has_condition:
            suggestions.append("请明确条件，如: 低于、跌破、超过、突破")

        return suggestions

    def get_available_indicators_brief(self) -> List[Dict]:
        """获取简化的指标列表，供前端显示"""
        return [
            {
                'code': ind['code'],
                'name': ind['name'],
                'category': ind['category'],
                'latest': ind['latest_value'],
            }
            for ind in self.indicators[:30]  # 限制数量
        ]


def ai_parse_invalidation_logic(user_input: str) -> Dict:
    """
    AI 解析证伪逻辑的入口函数

    Args:
        user_input: 用户输入的自然语言描述

    Returns:
        解析结果
    """
    helper = AIInvalidationHelper()
    return helper.parse_invalidation_logic(user_input)


def get_available_indicators() -> List[Dict]:
    """获取可用的指标列表"""
    helper = AIInvalidationHelper()
    return helper.get_available_indicators_brief()
