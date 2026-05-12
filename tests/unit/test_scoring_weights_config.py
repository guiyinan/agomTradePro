"""
股票评分权重配置单元测试

测试评分权重配置的加载、验证和使用
"""


import pytest

from apps.equity.domain.entities import (
    ScoringWeightConfig,
)
from apps.equity.domain.services import StockScreener


class TestScoringWeightConfigEntity:
    """测试 ScoringWeightConfig 实体"""

    def test_default_config_is_valid(self):
        """测试默认配置是有效的"""
        config = ScoringWeightConfig(name="测试配置")

        # 验证权重总和为 1.0
        assert abs(config.growth_weight + config.profitability_weight + config.valuation_weight - 1.0) < 0.01
        assert abs(config.revenue_growth_weight + config.profit_growth_weight - 1.0) < 0.01

    def test_custom_config_with_valid_weights(self):
        """测试自定义有效配置"""
        config = ScoringWeightConfig(
            name="成长型配置",
            growth_weight=0.5,
            profitability_weight=0.35,
            valuation_weight=0.15,
            revenue_growth_weight=0.6,
            profit_growth_weight=0.4
        )

        # 验证权重总和
        assert abs(config.growth_weight + config.profitability_weight + config.valuation_weight - 1.0) < 0.01

    def test_invalid_dimension_weights_raise_error(self):
        """测试无效的维度权重会抛出错误"""
        with pytest.raises(ValueError, match="评分维度权重总和必须为 1.0"):
            ScoringWeightConfig(
                name="无效配置",
                growth_weight=0.5,
                profitability_weight=0.3,
                valuation_weight=0.3  # 总和为 1.1
            )

    def test_get_total_score(self):
        """测试计算总评分"""
        config = ScoringWeightConfig(
            name="测试配置",
            growth_weight=0.4,
            profitability_weight=0.4,
            valuation_weight=0.2,
            revenue_growth_weight=0.5,
            profit_growth_weight=0.5
        )

        score = config.get_total_score(
            revenue_growth_percentile=0.8,
            profit_growth_percentile=0.6,
            roe_percentile=0.7,
            pe_percentile=0.3
        )

        # 总分 = 0.7 * 0.4 + 0.7 * 0.4 + 0.7 * 0.2 = 0.7
        assert abs(score - 0.7) < 0.01


class TestStockScreenerWithConfig:
    """测试 StockScreener 使用配置"""

    def test_screener_uses_default_config_when_none_provided(self):
        """测试未提供配置时使用默认配置"""
        screener = StockScreener()
        assert screener.scoring_config is not None
        assert screener.scoring_config.name == "默认配置"

    def test_screener_uses_provided_config(self):
        """测试使用提供的配置"""
        custom_config = ScoringWeightConfig(
            name="成长型配置",
            growth_weight=0.5,
            profitability_weight=0.35,
            valuation_weight=0.15
        )
        screener = StockScreener(scoring_config=custom_config)
        assert screener.scoring_config.name == "成长型配置"
