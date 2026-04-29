"""
Unit tests for Currency Unit Conversion

测试货币单位转换的正确性
"""

import pytest

from apps.macro.domain.entities import (
    UNIT_CONVERSION_FACTORS,
    convert_currency_value,
    normalize_currency_unit,
)


class TestNormalizeCurrencyUnit:
    """货币单位转换测试"""

    def test_cny_yuan_to_yuan(self):
        """测试：元转元"""
        value, unit = normalize_currency_unit(100, "元")
        assert value == 100
        assert unit == "元"

    def test_cny_wan_to_yuan(self):
        """测试：万元转元"""
        value, unit = normalize_currency_unit(1.5, "万元")
        assert value == 15000
        assert unit == "元"

    def test_cny_qian_to_yuan(self):
        """测试：千元转元"""
        value, unit = normalize_currency_unit(2, "千元")
        assert value == 2000
        assert unit == "元"

    def test_cny_yi_to_yuan(self):
        """测试：亿元转元"""
        value, unit = normalize_currency_unit(1.5, "亿元")
        assert value == 150000000
        assert unit == "元"

    def test_usd_wan_to_yuan_with_exchange_rate(self):
        """测试：万美元转元（含汇率）"""
        value, unit = normalize_currency_unit(100, "万美元", exchange_rate=7.2)
        assert value == 7200000  # 100 * 10000 * 7.2
        assert unit == "元"

    def test_usd_yi_to_yuan_with_exchange_rate(self):
        """测试：亿美元转元（含汇率）"""
        value, unit = normalize_currency_unit(1.0, "亿美元", exchange_rate=7.2)
        assert value == 720000000  # 1 * 100000000 * 7.2
        assert unit == "元"

    def test_usd_shi_to_yuan_with_exchange_rate(self):
        """测试：十亿美元转元（含汇率）"""
        value, unit = normalize_currency_unit(1.0, "十亿美元", exchange_rate=7.2)
        assert value == 7200000000  # 1 * 1000000000 * 7.2
        assert unit == "元"

    def test_usd_unit_without_exchange_rate_uses_1(self):
        """测试：美元单位不传汇率，默认使用 1.0"""
        value, unit = normalize_currency_unit(1.0, "亿美元")
        assert value == 100000000  # 1 * 100000000 * 1.0
        assert unit == "元"

    def test_unknown_unit_preserved(self):
        """测试：未知单位保持原值"""
        value, unit = normalize_currency_unit(100, "UnknownUnit")
        assert value == 100
        assert unit == "UnknownUnit"


class TestConversionFactors:
    """转换因子测试"""

    def test_conversion_factors_completeness(self):
        """测试：转换因子表完整性"""
        expected_factors = {
            "元": 1,
            "千元": 1000,
            "万元": 10000,
            "亿元": 100000000,
            "万亿元": 1000000000000,
            "万美元": 10000,
            "百万美元": 1000000,
            "亿美元": 100000000,
            "十亿美元": 1000000000,
            "万亿美元": 10000000000000,
        }

        for unit, factor in expected_factors.items():
            assert unit in UNIT_CONVERSION_FACTORS
            assert UNIT_CONVERSION_FACTORS[unit] == factor


class TestRealWorldScenarios:
    """真实场景测试"""

    def test_convert_currency_value_from_yuan_to_yi(self):
        """测试：元与亿元之间可双向转换"""
        value, unit = convert_currency_value(3152200000000, "元", "亿元")
        assert value == 31522
        assert unit == "亿元"

    def test_china_forex_reserves(self):
        """测试：中国外汇储备（真实场景）"""
        # 中国外汇储备约 3.2 万亿美元
        # 假设数据源返回的是 32000 亿美元
        value, unit = normalize_currency_unit(32000, "亿美元", exchange_rate=7.2)

        assert value == 23040000000000  # 32000 * 100000000 * 7.2
        assert unit == "元"

    def test_trade_surplus(self):
        """测试：贸易顺差（真实场景）"""
        # 贸易顺差 500 亿美元
        value, unit = normalize_currency_unit(500, "亿美元", exchange_rate=7.2)

        assert value == 360000000000  # 500 * 100000000 * 7.2
        assert unit == "元"

    def test_usd_conversion_impact(self):
        """测试：美元转换对结果的影响"""
        # 同样数值，有汇率和无汇率的差异
        value_with_rate, _ = normalize_currency_unit(1.0, "亿美元", exchange_rate=7.2)
        value_without_rate, _ = normalize_currency_unit(1.0, "亿美元", exchange_rate=1.0)

        # 有汇率应该是无汇率的 7.2 倍
        assert value_with_rate == value_without_rate * 7.2
        # 误差应该是 620% （这是 bug 修复带来的正确差异）
        assert abs((value_with_rate - value_without_rate) / value_without_rate * 100 - 620) < 0.1
