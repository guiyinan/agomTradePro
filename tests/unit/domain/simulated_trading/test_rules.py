"""
模拟盘Domain层业务规则测试

测试PositionSizingRule和TradingConstraintRule
"""
from datetime import date

import pytest

from apps.simulated_trading.domain.entities import AccountType, Position, SimulatedAccount
from apps.simulated_trading.domain.rules import PositionSizingRule, TradingConstraintRule


class TestPositionSizingRule:
    """测试仓位管理规则"""

    def test_calculate_buy_quantity_high_score(self):
        """测试计算买入数量 - 高评分资产"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            max_position_pct=20.0,
            max_total_position_pct=95.0
        )

        # 高评分资产(90分)
        quantity = PositionSizingRule.calculate_buy_quantity(
            account=account,
            asset_price=10.0,
            asset_score=90.0,
            existing_positions=[]
        )

        # 预期: 100000 * 0.2 * 0.9 / 10 = 1800, 向下取整到100的倍数 = 1800
        assert quantity == 1800

    def test_calculate_buy_quantity_low_score(self):
        """测试计算买入数量 - 低评分资产"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            max_position_pct=20.0,
            max_total_position_pct=95.0
        )

        # 低评分资产(65分)
        quantity = PositionSizingRule.calculate_buy_quantity(
            account=account,
            asset_price=10.0,
            asset_score=65.0,
            existing_positions=[]
        )

        # 预期: 100000 * 0.2 * 0.65 / 10 = 1300, 取整到100的倍数 = 1300
        assert quantity == 1300

    def test_calculate_buy_quantity_expensive_asset(self):
        """测试计算买入数量 - 高价资产(数量为0)"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=10000.0,
            current_cash=10000.0,
            current_market_value=0.0,
            total_value=10000.0,
            max_position_pct=20.0
        )

        # 高价资产(500元一股),评分80
        quantity = PositionSizingRule.calculate_buy_quantity(
            account=account,
            asset_price=500.0,
            asset_score=80.0,
            existing_positions=[]
        )

        # 预期: 10000 * 0.2 * 0.8 / 500 = 3.2, 取整到100的倍数 = 0
        assert quantity == 0

    def test_should_sell_position_signal_invalid(self):
        """测试卖出判断 - 信号失效"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=1000,
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=12.0,
            market_value=12000.0,
            unrealized_pnl=2000.0,
            unrealized_pnl_pct=20.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        should_sell = PositionSizingRule.should_sell_position(
            position=position,
            signal_valid=False,  # 信号失效
            regime_match=True,
            stop_loss_pct=None
        )

        assert should_sell is True

    def test_should_sell_position_regime_mismatch(self):
        """测试卖出判断 - Regime不匹配"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=1000,
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=12.0,
            market_value=12000.0,
            unrealized_pnl=2000.0,
            unrealized_pnl_pct=20.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        should_sell = PositionSizingRule.should_sell_position(
            position=position,
            signal_valid=True,
            regime_match=False,  # Regime不匹配
            stop_loss_pct=None
        )

        assert should_sell is True

    def test_should_sell_position_stop_loss(self):
        """测试卖出判断 - 触发止损"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=1000,
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=8.5,
            market_value=8500.0,
            unrealized_pnl=-1500.0,
            unrealized_pnl_pct=-15.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        should_sell = PositionSizingRule.should_sell_position(
            position=position,
            signal_valid=True,
            regime_match=True,
            stop_loss_pct=10.0  # 10%止损
        )

        # 浮亏15%,超过10%止损线,应该卖出
        assert should_sell is True

    def test_should_not_sell_position(self):
        """测试不卖出判断 - 所有条件满足"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=1000,
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=12.0,
            market_value=12000.0,
            unrealized_pnl=2000.0,
            unrealized_pnl_pct=20.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        should_sell = PositionSizingRule.should_sell_position(
            position=position,
            signal_valid=True,
            regime_match=True,
            stop_loss_pct=10.0
        )

        assert should_sell is False


class TestTradingConstraintRule:
    """测试交易约束规则"""

    def test_validate_buy_order_success(self):
        """测试验证买入订单 - 成功"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            auto_trading_enabled=True,
            is_active=True,
            commission_rate=0.0003,
            slippage_rate=0.001
        )

        valid, reason = TradingConstraintRule.validate_buy_order(
            account=account,
            asset_code="000001.SZ",
            quantity=1000,
            price=10.0
        )

        assert valid is True
        assert reason == ""

    def test_validate_buy_order_auto_trading_disabled(self):
        """测试验证买入订单 - 自动交易未启用"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            auto_trading_enabled=False,  # 自动交易未启用
            is_active=True
        )

        valid, reason = TradingConstraintRule.validate_buy_order(
            account=account,
            asset_code="000001.SZ",
            quantity=1000,
            price=10.0
        )

        assert valid is False
        assert "自动交易未启用" in reason

    def test_validate_buy_order_insufficient_cash(self):
        """测试验证买入订单 - 现金不足"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=10000.0,
            current_cash=5000.0,
            current_market_value=0.0,
            total_value=5000.0,
            auto_trading_enabled=True,
            is_active=True,
            commission_rate=0.0003,
            slippage_rate=0.001
        )

        valid, reason = TradingConstraintRule.validate_buy_order(
            account=account,
            asset_code="000001.SZ",
            quantity=1000,
            price=10.0  # 需要10015元,但只有5000元
        )

        assert valid is False
        assert "现金不足" in reason

    def test_validate_buy_order_invalid_quantity(self):
        """测试验证买入订单 - 数量不是100的倍数"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            auto_trading_enabled=True,
            is_active=True
        )

        valid, reason = TradingConstraintRule.validate_buy_order(
            account=account,
            asset_code="000001.SZ",
            quantity=150,  # 不是100的倍数
            price=10.0
        )

        assert valid is False
        assert "100的倍数" in reason

    def test_validate_sell_order_success(self):
        """测试验证卖出订单 - 成功"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=1000,
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=12.0,
            market_value=12000.0,
            unrealized_pnl=2000.0,
            unrealized_pnl_pct=20.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        valid, reason = TradingConstraintRule.validate_sell_order(
            position=position,
            quantity=500
        )

        assert valid is True
        assert reason == ""

    def test_validate_sell_order_insufficient_quantity(self):
        """测试验证卖出订单 - 可卖数量不足"""
        position = Position(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000,
            available_quantity=500,  # 只有500可卖(T+1)
            avg_cost=10.0,
            total_cost=10000.0,
            current_price=12.0,
            market_value=12000.0,
            unrealized_pnl=2000.0,
            unrealized_pnl_pct=20.0,
            first_buy_date=date.today(),
            last_update_date=date.today()
        )

        valid, reason = TradingConstraintRule.validate_sell_order(
            position=position,
            quantity=1000  # 想卖1000,但只有500可卖
        )

        assert valid is False
        assert "可卖数量不足" in reason
