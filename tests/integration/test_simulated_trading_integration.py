"""
模拟盘交易模块集成测试

端到端测试：
- 账户创建与管理
- 买入/卖出订单执行
- 持仓更新
- 绩效计算
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.test import TestCase

from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.application.use_cases import (
    CreateSimulatedAccountUseCase,
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
    ListAccountsUseCase,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoFeeConfigRepository,
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)


@pytest.mark.django_db
class TestSimulatedTradingE2E(TestCase):
    """模拟盘交易端到端测试"""

    def setUp(self):
        """设置测试环境"""
        # 创建费率配置
        self.fee_config = FeeConfigModel.objects.create(
            config_name='标准费率',
            asset_type='equity',
            commission_rate_buy=0.0003,
            commission_rate_sell=0.0003,
            min_commission=5.0,
            stamp_duty_rate=0.001,
            transfer_fee_rate=0.00002,
            min_transfer_fee=1.0,
            slippage_rate=0.001,
            is_active=True,
        )

        # 初始化仓储
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

    def test_complete_trading_workflow(self):
        """
        测试完整的交易流程：
        1. 创建账户
        2. 买入股票
        3. 检查持仓
        4. 卖出股票
        5. 计算绩效
        """
        # ========== 1. 创建账户 ==========
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        account = create_use_case.execute(
            account_name='集成测试账户',
            initial_capital=100000.00,
            max_position_pct=20.0,
            stop_loss_pct=10.0,
            commission_rate=0.0003,
            slippage_rate=0.001
        )

        self.assertIsNotNone(account.account_id)
        self.assertEqual(account.account_name, '集成测试账户')
        self.assertEqual(float(account.initial_capital), 100000.00)
        self.assertEqual(float(account.current_cash), 100000.00)

        # ========== 2. 买入股票 ==========
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        # 买入第一笔
        trade1 = buy_use_case.execute(
            account_id=account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=12.50,
            reason='测试买入1'
        )

        self.assertEqual(trade1.asset_code, '000001.SZ')
        self.assertEqual(trade1.quantity, 1000)
        self.assertEqual(float(trade1.price), 12.50)

        # 买入第二笔
        trade2 = buy_use_case.execute(
            account_id=account.account_id,
            asset_code='600519.SH',
            asset_name='贵州茅台',
            asset_type='equity',
            quantity=100,  # A股必须是100的倍数
            price=100.00,  # 降低价格
            reason='测试买入2'
        )

        # ========== 3. 检查持仓 ==========
        positions = self.position_repo.get_by_account(account.account_id)
        self.assertEqual(len(positions), 2)

        position1 = self.position_repo.get_position(account.account_id, '000001.SZ')
        self.assertIsNotNone(position1)
        self.assertEqual(position1.quantity, 1000)
        self.assertEqual(float(position1.avg_cost), 12.50)

        position2 = self.position_repo.get_position(account.account_id, '600519.SH')
        self.assertIsNotNone(position2)
        self.assertEqual(position2.quantity, 100)

        # 检查账户资金
        updated_account = self.account_repo.get_by_id(account.account_id)
        expected_cash = 100000.00 - trade1.total_cost - trade2.total_cost
        self.assertAlmostEqual(float(updated_account.current_cash), expected_cash, places=2)
        self.assertEqual(updated_account.total_trades, 2)

        # ========== 4. 卖出股票 ==========
        sell_use_case = ExecuteSellOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        # 卖出第一笔（盈利）
        sell_trade1 = sell_use_case.execute(
            account_id=account.account_id,
            asset_code='000001.SZ',
            quantity=500,
            price=13.00,  # 盈利
            reason='测试卖出'
        )

        self.assertEqual(sell_trade1.asset_code, '000001.SZ')
        self.assertEqual(sell_trade1.quantity, 500)
        self.assertGreater(sell_trade1.realized_pnl, 0)  # 应该盈利

        # 检查持仓减少
        position1_after = self.position_repo.get_position(account.account_id, '000001.SZ')
        self.assertEqual(position1_after.quantity, 500)  # 剩余500股

        # 卖出第二笔（亏损）
        sell_trade2 = sell_use_case.execute(
            account_id=account.account_id,
            asset_code='600519.SH',
            quantity=100,  # 全部卖出
            price=90.00,  # 亏损（100 -> 90）
            reason='测试卖出'
        )

        self.assertEqual(sell_trade2.quantity, 100)
        self.assertLess(sell_trade2.realized_pnl, 0)  # 应该亏损

        # 检查持仓清空
        position2_after = self.position_repo.get_position(account.account_id, '600519.SH')
        self.assertIsNone(position2_after)  # 持仓已清空

        # ========== 5. 计算绩效 ==========
        performance_use_case = GetAccountPerformanceUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        result = performance_use_case.execute(account.account_id)

        self.assertEqual(result['account'].account_id, account.account_id)
        self.assertEqual(result['total_positions'], 1)  # 只剩一个持仓
        self.assertEqual(result['total_trades'], 4)  # 2买+2卖
        self.assertIn('performance', result)

        # 检查交易记录
        trades = self.trade_repo.get_by_account(account.account_id)
        self.assertEqual(len(trades), 4)


@pytest.mark.django_db
class TestPositionSizing(TestCase):
    """测试仓位管理"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='仓位测试账户',
            initial_capital=100000.00,
            max_position_pct=20.0,
        )

        self.buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

    def test_max_position_limit(self):
        """测试单资产最大持仓限制"""
        # 尝试买入超过最大持仓比例的股票
        # 账户总资产10万，最大持仓20% = 2万
        # 股价100元，最多买200股

        with self.assertRaises(ValueError) as ctx:
            self.buy_use_case.execute(
                account_id=self.account.account_id,
                asset_code='000001.SZ',
                asset_name='平安银行',
                asset_type='equity',
                quantity=300,  # 超过限制
                price=100.00,
            )

        self.assertIn('超过最大持仓比例', str(ctx.exception))

    def test_insufficient_cash(self):
        """测试资金不足"""
        # 账户只有10万，尝试买入更多
        with self.assertRaises(ValueError) as ctx:
            self.buy_use_case.execute(
                account_id=self.account.account_id,
                asset_code='000001.SZ',
                asset_name='平安银行',
                asset_type='equity',
                quantity=10000,  # 需要约100万
                price=100.00,
            )

        self.assertIn('现金不足(需要', str(ctx.exception))


@pytest.mark.django_db
class TestPerformanceCalculation(TestCase):
    """测试绩效计算"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='绩效测试账户',
            initial_capital=100000.00,
            max_position_pct=100.0,
        )

        # 执行一些交易
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )
        sell_use_case = ExecuteSellOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        # 买入
        buy_use_case.execute(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
        )

        # 卖出（盈利）
        sell_use_case.execute(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            quantity=500,
            price=11.00,  # 10%盈利
        )

        # 卖出（亏损）
        buy_use_case.execute(
            account_id=self.account.account_id,
            asset_code='600519.SH',
            asset_name='贵州茅台',
            asset_type='equity',
            quantity=100,
            price=900.00,
        )

        sell_use_case.execute(
            account_id=self.account.account_id,
            asset_code='600519.SH',
            quantity=100,
            price=855.00,  # 5%亏损
        )

    def test_total_return_calculation(self):
        """测试总收益率计算"""
        calculator = PerformanceCalculator()
        metrics = calculator.calculate_and_update_performance(
            account_id=self.account.account_id,
            trade_date=date.today()
        )

        self.assertIn('total_return', metrics)
        self.assertIn('annual_return', metrics)

        # 验证账户已更新
        updated_account = self.account_repo.get_by_id(self.account.account_id)
        self.assertIsNotNone(updated_account.total_return)

    def test_win_rate_calculation(self):
        """测试胜率计算"""
        calculator = PerformanceCalculator()
        metrics = calculator.calculate_and_update_performance(
            account_id=self.account.account_id,
            trade_date=date.today()
        )

        self.assertIn('win_rate', metrics)
        self.assertIn('winning_trades', metrics)

        # 应该有3笔完成的交易（2卖+1买入后剩余持仓）
        # 胜率应该是50%（1盈利1亏损）
        # 但实际上有3个sell交易才会被计入胜率


@pytest.mark.django_db
class TestFeeConfiguration(TestCase):
    """测试费率配置"""

    def test_fee_config_repository(self):
        """测试费率配置仓储"""
        repo = DjangoFeeConfigRepository()

        # 创建配置
        config = repo.create_config(
            config_name='低费率',
            asset_type='equity',
            commission_rate_buy=0.0001,
            commission_rate_sell=0.0001,
            min_commission=5.0,
            stamp_duty_rate=0.001,
            transfer_fee_rate=0.00002,
            min_transfer_fee=1.0,
            slippage_rate=0.0005,
        )

        self.assertIsNotNone(config.config_id)

        # 获取配置
        retrieved = repo.get_by_id(config.config_id)
        self.assertEqual(retrieved.config_name, '低费率')
        self.assertEqual(retrieved.commission_rate_buy, 0.0001)

        # 获取所有配置
        all_configs = repo.get_all_configs()
        self.assertGreater(len(all_configs), 0)


@pytest.mark.django_db
class TestAutoTradingWorkflow(TestCase):
    """测试自动交易工作流"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建启用自动交易的账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='自动交易测试',
            initial_capital=100000.00,
            auto_trading_enabled=True,
        )

    def test_auto_trading_enabled(self):
        """测试自动交易开关"""
        account = self.account_repo.get_by_id(self.account.account_id)
        self.assertTrue(account.auto_trading_enabled)

    def test_list_active_accounts(self):
        """测试列出活跃账户"""
        use_case = ListAccountsUseCase(self.account_repo)
        accounts = use_case.execute(active_only=True)

        self.assertGreater(len(accounts), 0)
        for acc in accounts:
            self.assertTrue(acc.is_active)


@pytest.mark.django_db
class TestStopLoss(TestCase):
    """测试止损功能"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建带止损的账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='止损测试账户',
            initial_capital=100000.00,
            stop_loss_pct=10.0,  # 10%止损
        )

    def test_stop_loss_validation(self):
        """测试止损验证"""
        # 账户设置了10%止损
        account = self.account_repo.get_by_id(self.account.account_id)
        self.assertEqual(account.stop_loss_pct, 10.0)

        # 买入股票
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )
        buy_use_case.execute(
            account_id=account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
        )

        # 检查持仓
        position = self.position_repo.get_position(account.account_id, '000001.SZ')
        self.assertIsNotNone(position)

        # 如果价格跌到9元（10%亏损），应该触发止损
        # 这个逻辑在自动交易引擎中实现
        # 这里只验证数据结构
        self.assertEqual(float(position.avg_cost), 10.00)


@pytest.mark.django_db
class testEquityCurve(TestCase):
    """测试净值曲线"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='净值曲线测试',
            initial_capital=100000.00,
        )

        # 执行交易
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            DjangoPositionRepository(),
            self.trade_repo
        )
        buy_use_case.execute(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
        )

    def test_get_equity_curve(self):
        """测试获取净值曲线"""
        calculator = PerformanceCalculator()
        curve = calculator.get_equity_curve(
            account_id=self.account.account_id,
            start_date=date.today(),
            end_date=date.today()
        )

        self.assertIsInstance(curve, list)
        # 应该至少有一天的数据
        self.assertGreater(len(curve), 0)

        # 验证数据结构（Phase 2 更新后的字段）
        if curve:
            point = curve[0]
            # 验证完整字段：cash/market_value/net_value/drawdown_pct
            self.assertIn('date', point)
            self.assertIn('net_value', point)
            self.assertIn('cash', point)
            self.assertIn('market_value', point)
            self.assertIn('drawdown_pct', point)

            # 验证净值 = 现金 + 持仓市值
            self.assertAlmostEqual(
                point['net_value'],
                point['cash'] + point['market_value'],
                places=2
            )
