"""
Unit tests for Volatility Target Control

测试波动率目标控制的正确性
"""

import pytest

from apps.account.domain.services import VolatilityTargetService


class TestVolatilityAdjustment:
    """波动率调整测试"""

    def test_no_adjustment_needed_within_tolerance(self):
        """测试：在容忍度内，不需要调整"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.18,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )

        # 18% vs 15%，波动率比率 1.2，在容忍度 1.2 内
        assert not result.should_reduce
        assert result.suggested_position_multiplier == 1.0
        assert result.volatility_ratio == 1.2

    def test_moderate_excess_proportional_reduction(self):
        """测试：中度超限，按比例降仓"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.25,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )

        # 波动率比率 1.67，超过容忍度
        assert result.should_reduce
        # target/current = 0.15/0.25 = 0.6
        assert result.suggested_position_multiplier == 0.6
        assert result.volatility_ratio == pytest.approx(1.6666666666666665)

    def test_severe_excess_hits_lower_bound(self):
        """测试：重度超限，触及下限"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.50,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )

        # 波动率比率 3.33，target/current = 0.3，但下限是 0.5
        assert result.should_reduce
        # 应该返回 0.5（下限），而不是 0.3
        assert result.suggested_position_multiplier == 0.5

    def test_exact_tolerance_boundary(self):
        """测试：恰好等于容忍度边界"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.18,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )

        # 18/15 = 1.2，恰好等于 1 + 0.2
        assert not result.should_reduce
        assert result.suggested_position_multiplier == 1.0

    def test_invalid_target_volatility(self):
        """测试：无效的目标波动率"""
        with pytest.raises(ValueError, match="target_volatility 必须大于0"):
            VolatilityTargetService.assess_volatility_adjustment(
                current_volatility=0.20,
                target_volatility=0.0,
            )

    def test_negative_volatility_raises_error(self):
        """测试：负波动率应该抛出异常"""
        with pytest.raises(ValueError, match="不能为负数"):
            VolatilityTargetService.assess_volatility_adjustment(
                current_volatility=-0.05,
                target_volatility=0.15,
            )


class TestVolatilityAdjustmentEdgeCases:
    """波动率调整边界测试"""

    def test_extremely_high_volatility(self):
        """测试：极高波动率"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=1.0,  # 100% 波动率
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.5,
        )

        # target/current = 0.15，应该返回下限 0.5
        assert result.should_reduce
        assert result.suggested_position_multiplier == 0.5

    def test_custom_max_reduction(self):
        """测试：自定义最大降仓幅度"""
        result = VolatilityTargetService.assess_volatility_adjustment(
            current_volatility=0.50,
            target_volatility=0.15,
            tolerance=0.2,
            max_reduction=0.3,  # 最多降 30%
        )

        # target/current = 0.3，下限 = 1 - 0.3 = 0.7
        # 应该返回 0.7，而不是 0.3
        assert result.should_reduce
        assert result.suggested_position_multiplier == 0.7
