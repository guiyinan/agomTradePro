"""
Unit tests for Stop Loss Service

测试止损服务的正确性，特别是正数语义
"""

import pytest

from apps.account.domain.services import StopLossService


class TestStopLossPositiveSemantics:
    """测试止损 API 的正数语义"""

    def test_fixed_stop_loss_with_positive_pct(self):
        """测试：固定止损使用正数百分比"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=89.0,
            highest_price=100.0,
            stop_loss_pct=0.10,  # 10% 止损（正数）
            stop_loss_type="fixed",
        )

        # 止损价 = 100 * (1 - 0.10) = 90
        # 当前价 89 < 90，应该触发止损
        assert result.should_trigger
        assert result.stop_price == 90.0
        assert "止损触发" in result.trigger_reason

    def test_fixed_stop_loss_not_triggered(self):
        """测试：固定止损未触发"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=95.0,
            highest_price=100.0,
            stop_loss_pct=0.10,  # 10% 止损
            stop_loss_type="fixed",
        )

        # 止损价 = 90，当前价 95 > 90，不应该触发
        assert not result.should_trigger
        assert result.stop_price == 90.0

    def test_negative_stop_loss_pct_raises_error(self):
        """测试：负数止损百分比应该抛出异常"""
        with pytest.raises(ValueError, match="stop_loss_pct 必须为正数或零"):
            StopLossService.check_stop_loss(
                entry_price=100.0,
                current_price=89.0,
                highest_price=100.0,
                stop_loss_pct=-0.10,  # 负数，应该报错
                stop_loss_type="fixed",
            )

    def test_stop_loss_pct_over_100_raises_error(self):
        """测试：超过 100% 的止损百分比应该抛出异常"""
        with pytest.raises(ValueError, match="stop_loss_pct 不能超过 100%"):
            StopLossService.check_stop_loss(
                entry_price=100.0,
                current_price=89.0,
                highest_price=100.0,
                stop_loss_pct=1.5,  # 150%，不合理
                stop_loss_type="fixed",
            )

    def test_zero_stop_loss_pct(self):
        """测试：0% 止损（零容忍，立即触发）"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=99.99,
            highest_price=100.0,
            stop_loss_pct=0.0,  # 0% 止损
            stop_loss_type="fixed",
        )

        # 止损价 = 100 * (1 - 0) = 100
        # 当前价 99.99 < 100，应该触发
        assert result.should_trigger
        assert result.stop_price == 100.0


class TestTrailingStopLoss:
    """测试移动止损"""

    def test_trailing_stop_loss_basic(self):
        """测试：移动止损基本功能"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=108.0,
            highest_price=120.0,
            stop_loss_pct=0.10,  # 10% 移动止损
            stop_loss_type="trailing",
        )

        # 移动止损价 = 120 * (1 - 0.10) = 108
        # 当前价 108 <= 108，应该触发
        assert result.should_trigger
        assert result.stop_price == 108.0
        assert "移动止损触发" in result.trigger_reason

    def test_trailing_stop_with_custom_trailing_pct(self):
        """测试：自定义移动止损百分比"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=115.0,
            highest_price=120.0,
            stop_loss_pct=0.10,
            trailing_stop_pct=0.05,  # 5% 移动止损
            stop_loss_type="trailing",
        )

        # 移动止损价 = 120 * (1 - 0.05) = 114
        # 当前价 115 > 114，不应该触发
        assert not result.should_trigger
        assert result.stop_price == 114.0

    def test_trailing_stop_negative_pct_raises_error(self):
        """测试：负数移动止损百分比应该抛出异常"""
        with pytest.raises(ValueError, match="trailing_stop_pct 必须为正数或零"):
            StopLossService.check_stop_loss(
                entry_price=100.0,
                current_price=108.0,
                highest_price=120.0,
                stop_loss_pct=0.10,
                trailing_stop_pct=-0.05,  # 负数，应该报错
                stop_loss_type="trailing",
            )


class TestStopLossEdgeCases:
    """测试止损边界情况"""

    def test_exact_stop_price(self):
        """测试：恰好等于止损价"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=90.0,
            highest_price=100.0,
            stop_loss_pct=0.10,
            stop_loss_type="fixed",
        )

        # 当前价 = 止损价，应该触发（<= 条件）
        assert result.should_trigger

    def test_profit_position(self    ):
        """测试：盈利持仓"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=110.0,
            highest_price=110.0,
            stop_loss_pct=0.10,
            stop_loss_type="fixed",
        )

        # 当前价高于开仓价，不应该触发止损
        assert not result.should_trigger
        # 未实现盈亏应该是正的
        assert result.unrealized_pnl_pct > 0

    def test_unknown_stop_loss_type(self):
        """测试：未知止损类型"""
        result = StopLossService.check_stop_loss(
            entry_price=100.0,
            current_price=80.0,
            highest_price=100.0,
            stop_loss_pct=0.10,
            stop_loss_type="unknown_type",
        )

        # 未知类型不应该触发
        assert not result.should_trigger
        assert "未触发" in result.trigger_reason
