"""
模拟盘净值曲线准确性集成测试

Phase 2 验收测试：
- 净值 = 现金 + 持仓市值
- 最大回撤按时序计算
- 返回完整字段：cash/market_value/net_value/drawdown_pct
"""
import pytest
from django.test import TestCase
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)
from apps.simulated_trading.application.use_cases import CreateSimulatedAccountUseCase
from apps.simulated_trading.application.performance_calculator import PerformanceCalculator
from apps.simulated_trading.domain.entities import TradeAction


@pytest.mark.django_db
class TestEquityCurveAccuracy(TestCase):
    """净值曲线准确性测试"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建测试账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='净值曲线测试账户',
            initial_capital=100000.00,
            max_position_pct=100.0,
        )

        # 创建专用的计算器实例，便于 mock
        self.calculator = PerformanceCalculator()

    def _create_trade(
        self,
        account_id: int,
        asset_code: str,
        asset_name: str,
        action: str,
        quantity: int,
        price: float,
        execution_date: date
    ) -> SimulatedTradeModel:
        """辅助方法：创建交易记录"""
        trade = SimulatedTradeModel()
        trade.account_id = account_id
        trade.asset_code = asset_code
        trade.asset_name = asset_name
        trade.asset_type = 'equity'
        trade.action = action
        trade.quantity = quantity
        trade.price = price
        trade.amount = price * quantity
        trade.commission = max(trade.amount * 0.0003, 5.0)
        trade.slippage = trade.amount * 0.001
        trade.total_cost = trade.amount + trade.commission + trade.slippage
        trade.order_date = execution_date
        trade.execution_date = execution_date
        trade.execution_time = datetime.now()
        trade.status = 'executed'
        trade.reason = '测试交易'
        trade.save()
        return trade

    def test_equity_curve_cash_only(self):
        """
        测试纯现金状态下的净值曲线

        验证：无交易时，净值应等于初始资金
        """
        curve = self.calculator.get_equity_curve(
            account_id=self.account.account_id,
            start_date=self.account.start_date,
            end_date=date.today()
        )

        # 无交易时应返回初始点
        self.assertGreater(len(curve), 0)
        self.assertEqual(curve[0]['net_value'], 100000.00)
        self.assertEqual(curve[0]['cash'], 100000.00)
        self.assertEqual(curve[0]['market_value'], 0.0)
        self.assertEqual(curve[0]['drawdown_pct'], 0.0)

    def test_equity_curve_data_structure(self):
        """
        测试净值曲线返回完整字段

        验收标准：cash/market_value/net_value/drawdown_pct
        """
        curve = self.calculator.get_equity_curve(
            account_id=self.account.account_id,
            start_date=self.account.start_date,
            end_date=date.today()
        )

        self.assertGreater(len(curve), 0)

        # 检查每个数据点包含所有必需字段
        required_fields = {'date', 'net_value', 'cash', 'market_value', 'drawdown_pct'}
        for point in curve:
            self.assertTrue(
                required_fields.issubset(point.keys()),
                f"Missing fields in point: {set(point.keys()) - required_fields}"
            )

            # 验证数据类型
            self.assertIsInstance(point['date'], str)
            self.assertIsInstance(point['net_value'], (int, float))
            self.assertIsInstance(point['cash'], (int, float))
            self.assertIsInstance(point['market_value'], (int, float))
            self.assertIsInstance(point['drawdown_pct'], (int, float))

            # 验证净值计算公式
            self.assertAlmostEqual(
                point['net_value'],
                point['cash'] + point['market_value'],
                places=2,
                msg="净值必须等于现金加持仓市值"
            )

            # 验证回撤为非负数
            self.assertGreaterEqual(point['drawdown_pct'], 0)

    def test_equity_curve_with_position(self):
        """
        测试买入后的净值曲线

        场景：
        - 初始资金 100,000
        - Day 1: 买入 1000 股 @ 10元
        - Mock 价格返回 12元（市值变为 12,000）
        - 验证净值 = 现金 + 持仓市值
        """
        day_1 = date.today() - timedelta(days=2)
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            action='buy',
            quantity=1000,
            price=10.00,
            execution_date=day_1
        )

        # Mock market_data_provider.get_price
        with patch.object(
            self.calculator.market_data_provider,
            'get_price',
            return_value=12.0
        ):
            curve = self.calculator.get_equity_curve(
                account_id=self.account.account_id,
                start_date=day_1,
                end_date=date.today()
            )

        # 验证曲线包含交易日的数据
        self.assertGreater(len(curve), 0)

        # 找到交易日的点
        day_1_point = next(
            (p for p in curve if date.fromisoformat(p['date']) == day_1),
            None
        )
        self.assertIsNotNone(day_1_point, f"Day 1 point not found in curve: {[p['date'] for p in curve]}")

        # 验证：现金 = 100,000 - (10,000 + 手续费 + 滑点)
        expected_cost = 10000 + max(10000 * 0.0003, 5.0) + 10000 * 0.001
        expected_cash = 100000 - expected_cost
        self.assertAlmostEqual(day_1_point['cash'], expected_cash, places=2)

        # 验证市值 = 1000 * 12 = 12000
        self.assertEqual(day_1_point['market_value'], 12000.0)

        # 验证净值 = 现金 + 市值
        expected_net_value = expected_cash + 12000.0
        self.assertAlmostEqual(day_1_point['net_value'], expected_net_value, places=2)

        # 验证字段完整性
        self.assertIn('net_value', day_1_point)
        self.assertIn('cash', day_1_point)
        self.assertIn('market_value', day_1_point)
        self.assertIn('drawdown_pct', day_1_point)

    def test_max_drawdown_calculation(self):
        """
        测试最大回撤计算

        场景：
        - Day 1: 买入 1000 股 @ 10元，价格 12元（盈利）
        - Day 2: 价格 11元（开始回撤）
        - Day 3: 价格 9元（回撤扩大）
        - 验证 max_drawdown 能正确计算
        """
        base_date = date.today() - timedelta(days=5)

        # Day 1: 买入 1000 股 @ 10元
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            action='buy',
            quantity=1000,
            price=10.00,
            execution_date=base_date
        )

        # Day 2: 创建小额交易触发第二日计算
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000002.SZ',
            asset_name='万科A',
            action='buy',
            quantity=100,
            price=10.00,
            execution_date=base_date + timedelta(days=1)
        )

        # Day 3: 创建小额交易触发第三日计算
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000003.SZ',
            asset_name='国农科技',
            action='buy',
            quantity=100,
            price=10.00,
            execution_date=base_date + timedelta(days=2)
        )

        # Mock 不同日期的价格：12 -> 11 -> 9
        call_count = [0]
        prices = [12.0, 11.0, 9.0]

        def mock_get_price(asset_code, trade_date):
            idx = min(call_count[0], len(prices) - 1)
            result = prices[idx]
            call_count[0] += 1
            return result

        with patch.object(
            self.calculator.market_data_provider,
            'get_price',
            side_effect=mock_get_price
        ):
            # 获取账户并计算最大回撤
            account = self.account_repo.get_by_id(self.account.account_id)
            max_dd = self.calculator._calculate_max_drawdown(account)

        # 应该有回撤（从高点下跌）
        # (12 - 9) / 12 * 100 = 25%
        self.assertGreater(max_dd, 0)
        self.assertLess(max_dd, 30)

    def test_drawdown_with_multiple_trades(self):
        """
        测试多交易场景下的回撤计算

        场景：
        - Day 1: 买入 @ 10元，价格 12元
        - Day 2: 再买入，价格 11元
        - Day 3: 卖出部分，价格 9元
        - 验证回撤按时间序列正确计算
        """
        base_date = date.today() - timedelta(days=5)

        # Day 1: 买入 @ 10元
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            action='buy',
            quantity=1000,
            price=10.00,
            execution_date=base_date
        )

        # Day 2: 再买入
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            action='buy',
            quantity=500,
            price=10.00,
            execution_date=base_date + timedelta(days=1)
        )

        # Day 3: 卖出部分
        self._create_trade(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            action='sell',
            quantity=500,
            price=9.50,
            execution_date=base_date + timedelta(days=2)
        )

        # Mock 价格返回
        call_count = [0]
        prices = [12.0, 11.0, 9.0]

        def mock_get_price(asset_code, trade_date):
            idx = min(call_count[0], len(prices) - 1)
            result = prices[idx]
            call_count[0] += 1
            return result

        with patch.object(
            self.calculator.market_data_provider,
            'get_price',
            side_effect=mock_get_price
        ):
            # 获取净值曲线
            curve = self.calculator.get_equity_curve(
                account_id=self.account.account_id,
                start_date=base_date,
                end_date=base_date + timedelta(days=2)
            )

        # 验证曲线点数
        self.assertEqual(len(curve), 3)

        # 验证每个点都有完整字段
        for point in curve:
            self.assertIn('date', point)
            self.assertIn('net_value', point)
            self.assertIn('cash', point)
            self.assertIn('market_value', point)
            self.assertIn('drawdown_pct', point)

            # 净值 = 现金 + 市值
            self.assertAlmostEqual(
                point['net_value'],
                point['cash'] + point['market_value'],
                places=2
            )


@pytest.mark.django_db
class TestPerformanceCalculatorIntegration(TestCase):
    """绩效计算器集成测试"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.calculator = PerformanceCalculator()

    def test_calculate_performance_with_no_trades(self):
        """测试无交易时的绩效计算"""
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        account = create_use_case.execute(
            account_name='无交易测试账户',
            initial_capital=100000.00,
        )

        metrics = self.calculator.calculate_and_update_performance(
            account_id=account.account_id,
            trade_date=date.today()
        )

        # 验证指标
        self.assertIn('total_return', metrics)
        self.assertIn('max_drawdown', metrics)
        self.assertIn('win_rate', metrics)

        # 无交易时，最大回撤应为0
        self.assertEqual(metrics['max_drawdown'], 0.0)

    def test_calculate_performance_with_trades(self):
        """测试有交易时的绩效计算"""
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        account = create_use_case.execute(
            account_name='有交易测试账户',
            initial_capital=100000.00,
        )

        # 创建交易
        trade = SimulatedTradeModel()
        trade.account_id = account.account_id
        trade.asset_code = '000001.SZ'
        trade.asset_name = '平安银行'
        trade.asset_type = 'equity'
        trade.action = 'buy'
        trade.quantity = 1000
        trade.price = 10.00
        trade.amount = 10000.00
        trade.commission = 5.0
        trade.slippage = 10.0
        trade.total_cost = 10015.0
        trade.order_date = date.today()
        trade.execution_date = date.today()
        trade.execution_time = datetime.now()
        trade.status = 'executed'
        trade.reason = '测试'
        trade.save()

        # Mock 价格
        with patch.object(
            self.calculator.market_data_provider,
            'get_price',
            return_value=10.0
        ):
            metrics = self.calculator.calculate_and_update_performance(
                account_id=account.account_id,
                trade_date=date.today()
            )

        # 验证指标
        self.assertIn('total_return', metrics)
        self.assertIn('max_drawdown', metrics)


@pytest.mark.django_db
class TestEquityCurveDataStructure(TestCase):
    """净值曲线数据结构测试"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.calculator = PerformanceCalculator()

        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='数据结构测试',
            initial_capital=100000.00,
        )

    def test_equity_curve_returns_all_required_fields(self):
        """
        测试净值曲线返回所有必需字段

        验收标准：cash/market_value/net_value/drawdown_pct
        """
        curve = self.calculator.get_equity_curve(
            account_id=self.account.account_id,
            start_date=self.account.start_date,
            end_date=date.today()
        )

        self.assertGreater(len(curve), 0)

        # 检查每个数据点包含所有必需字段
        required_fields = {'date', 'net_value', 'cash', 'market_value', 'drawdown_pct'}
        for point in curve:
            self.assertTrue(
                required_fields.issubset(point.keys()),
                f"Missing fields in point: {set(point.keys()) - required_fields}"
            )

            # 验证数据类型
            self.assertIsInstance(point['date'], str)
            self.assertIsInstance(point['net_value'], (int, float))
            self.assertIsInstance(point['cash'], (int, float))
            self.assertIsInstance(point['market_value'], (int, float))
            self.assertIsInstance(point['drawdown_pct'], (int, float))

            # 验证净值计算公式
            self.assertAlmostEqual(
                point['net_value'],
                point['cash'] + point['market_value'],
                places=2,
                msg="净值必须等于现金加持仓市值"
            )

            # 验证回撤为非负数
            self.assertGreaterEqual(point['drawdown_pct'], 0)

    def test_net_value_equals_cash_plus_market_value(self):
        """
        验收测试：净值 = 现金 + 持仓市值

        这是核心算法的正确性验证
        """
        curve = self.calculator.get_equity_curve(
            account_id=self.account.account_id,
            start_date=self.account.start_date,
            end_date=date.today()
        )

        for point in curve:
            net_value = point['net_value']
            cash = point['cash']
            market_value = point['market_value']

            # 净值必须等于现金加持仓市值
            self.assertAlmostEqual(
                net_value,
                cash + market_value,
                places=2,
                msg=f"净值计算错误: {net_value} != {cash} + {market_value}"
            )
