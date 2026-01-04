"""
模拟盘Domain层实体测试

测试FeeConfig、SimulatedAccount、Position、SimulatedTrade实体
"""
import pytest
from datetime import date, datetime
from apps.simulated_trading.domain.entities import (
    FeeConfig,
    SimulatedAccount,
    Position,
    SimulatedTrade,
    AccountType,
    TradeAction,
    OrderStatus
)


class TestFeeConfig:
    """测试费率配置实体"""

    def test_calculate_buy_fee_equity_standard(self):
        """测试计算买入费用 - 股票标准费率"""
        config = FeeConfig(
            config_id=1,
            config_name="标准费率",
            asset_type="equity",
            commission_rate_buy=0.0003,
            min_commission=5.0,
            stamp_duty_rate=0.001,
            transfer_fee_rate=0.00002,
            slippage_rate=0.001
        )

        # 买入10000元上海市场股票
        fees = config.calculate_buy_fee(10000.0, is_shanghai=True)

        assert fees['commission'] == 5.0  # 最低手续费
        assert fees['transfer_fee'] == 0.2  # 10000 * 0.00002
        assert fees['stamp_duty'] == 0.0   # 买入无印花税
        assert fees['slippage'] == 10.0    # 10000 * 0.001
        assert fees['total_fee'] == 15.2   # 5.0 + 0.2 + 10.0

    def test_calculate_sell_fee_equity_standard(self):
        """测试计算卖出费用 - 股票标准费率"""
        config = FeeConfig(
            config_id=1,
            config_name="标准费率",
            asset_type="equity",
            commission_rate_sell=0.0003,
            min_commission=5.0,
            stamp_duty_rate=0.001,
            transfer_fee_rate=0.00002,
            slippage_rate=0.001
        )

        # 卖出10000元上海市场股票
        fees = config.calculate_sell_fee(10000.0, is_shanghai=True)

        assert fees['commission'] == 5.0   # 最低手续费
        assert fees['stamp_duty'] == 10.0  # 10000 * 0.001
        assert fees['transfer_fee'] == 0.2 # 10000 * 0.00002
        assert fees['slippage'] == 10.0    # 10000 * 0.001
        assert fees['total_fee'] == 25.2   # 5.0 + 10.0 + 0.2 + 10.0

    def test_calculate_buy_fee_fund(self):
        """测试计算买入费用 - 基金(无印花税、无过户费)"""
        config = FeeConfig(
            config_id=2,
            config_name="基金费率",
            asset_type="fund",
            commission_rate_buy=0.0,  # 基金免佣
            min_commission=0.0,
            slippage_rate=0.0005
        )

        # 买入10000元基金
        fees = config.calculate_buy_fee(10000.0, is_shanghai=True)

        assert fees['commission'] == 0.0
        assert fees['transfer_fee'] == 0.0  # 基金无过户费
        assert fees['stamp_duty'] == 0.0
        assert fees['slippage'] == 5.0      # 10000 * 0.0005
        assert fees['total_fee'] == 5.0

    def test_large_amount_commission(self):
        """测试大额交易手续费(超过最低手续费)"""
        config = FeeConfig(
            config_id=1,
            config_name="标准费率",
            asset_type="equity",
            commission_rate_buy=0.0003,
            min_commission=5.0,
            slippage_rate=0.001
        )

        # 买入100万元
        fees = config.calculate_buy_fee(1000000.0, is_shanghai=False)

        assert fees['commission'] == 300.0  # 1000000 * 0.0003 (远超5元)
        assert fees['slippage'] == 1000.0
        assert fees['total_fee'] == 1300.0


class TestSimulatedAccount:
    """测试模拟账户实体"""

    def test_create_account(self):
        """测试创建模拟账户"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0
        )

        assert account.account_id == 1
        assert account.account_name == "测试账户"
        assert account.initial_capital == 100000.0
        assert account.total_value == 100000.0
        assert account.auto_trading_enabled is True

    def test_available_cash_for_buy(self):
        """测试计算可用买入现金"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            max_total_position_pct=95.0
        )

        available = account.available_cash_for_buy()
        assert available == 95000.0  # 100000 * 0.95

    def test_max_position_value(self):
        """测试计算单资产最大持仓市值"""
        account = SimulatedAccount(
            account_id=1,
            account_name="测试账户",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
            max_position_pct=20.0
        )

        max_value = account.max_position_value()
        assert max_value == 20000.0  # 100000 * 0.2


class TestPosition:
    """测试持仓实体"""

    def test_create_position(self):
        """测试创建持仓"""
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

        assert position.asset_code == "000001.SZ"
        assert position.quantity == 1000
        assert position.unrealized_pnl == 2000.0
        assert position.unrealized_pnl_pct == 20.0


class TestSimulatedTrade:
    """测试交易记录实体"""

    def test_create_buy_trade(self):
        """测试创建买入交易记录"""
        trade = SimulatedTrade(
            trade_id=1,
            account_id=1,
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            action=TradeAction.BUY,
            quantity=1000,
            price=10.0,
            amount=10000.0,
            commission=5.0,
            slippage=10.0,
            total_cost=10015.0,
            order_date=date.today(),
            execution_date=date.today(),
            execution_time=datetime.now(),
            status=OrderStatus.EXECUTED
        )

        assert trade.action == TradeAction.BUY
        assert trade.quantity == 1000
        assert trade.total_cost == 10015.0
        assert trade.status == OrderStatus.EXECUTED
