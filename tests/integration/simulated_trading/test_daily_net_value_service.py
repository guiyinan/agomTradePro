"""
每日净值记录服务集成测试

验证：
1. record_and_update_performance 正确记录净值
2. 净值记录包含完整的字段（现金、市值、净值、收益率、回撤）
3. 绩效指标与净值曲线一致
4. 最大回撤按时序准确计算
5. 自动交易引擎在交易后自动调用绩效更新
"""
import pytest
from django.test import TestCase
from datetime import date, timedelta
from decimal import Decimal

from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    PositionModel,
    SimulatedTradeModel,
    DailyNetValueModel,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoSimulatedAccountRepository,
    DjangoPositionRepository,
    DjangoTradeRepository,
)
from apps.simulated_trading.application.use_cases import (
    CreateSimulatedAccountUseCase,
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
    GetAccountPerformanceUseCase,
)
from apps.simulated_trading.application.daily_net_value_service import DailyNetValueService
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine, MockMarketDataProvider


@pytest.mark.django_db
class TestDailyNetValueService(TestCase):
    """每日净值记录服务测试"""

    def setUp(self):
        """设置测试环境"""
        self.account_repo = DjangoSimulatedAccountRepository()
        self.position_repo = DjangoPositionRepository()
        self.trade_repo = DjangoTradeRepository()

        # 创建账户
        create_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.account = create_use_case.execute(
            account_name='净值服务测试账户',
            initial_capital=100000.00,
            auto_trading_enabled=True,
            commission_rate=0.0003,
            slippage_rate=0.001
        )

        # 初始化净值服务
        self.net_value_service = DailyNetValueService(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo
        )

    def test_record_net_value_after_buy(self):
        """测试买入后记录净值"""
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )
        trade_date = date.today()

        # 执行买入
        buy_use_case.execute(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
            reason='测试买入'
        )

        # 记录净值
        metrics = self.net_value_service.record_and_update_performance(
            account_id=self.account.account_id,
            record_date=trade_date
        )

        # 验证净值记录已创建
        net_value_record = DailyNetValueModel.objects.get(
            account_id=self.account.account_id,
            record_date=trade_date
        )

        self.assertIsNotNone(net_value_record)

        # 验证净值 = 现金 + 持仓市值
        account = self.account_repo.get_by_id(self.account.account_id)
        expected_net_value = float(account.current_cash + account.current_market_value)
        self.assertAlmostEqual(float(net_value_record.net_value), expected_net_value, places=2)
        self.assertAlmostEqual(float(net_value_record.cash), float(account.current_cash), places=2)
        self.assertAlmostEqual(float(net_value_record.market_value), float(account.current_market_value), places=2)

        # 验证累计收益率
        expected_cumulative_return = ((expected_net_value - float(self.account.initial_capital)) / float(self.account.initial_capital)) * 100
        self.assertAlmostEqual(net_value_record.cumulative_return, expected_cumulative_return, places=2)

    def test_equity_curve_consistency(self):
        """测试净值曲线一致性"""
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        trade_date = date.today()

        # 创建多日数据
        price_sequence = [10.00, 10.50, 11.00, 10.50, 10.00]

        for i, price in enumerate(price_sequence):
            current_date = trade_date + timedelta(days=i)

            if i == 0:
                # 第一天买入
                buy_use_case.execute(
                    account_id=self.account.account_id,
                    asset_code='000001.SZ',
                    asset_name='平安银行',
                    asset_type='equity',
                    quantity=1000,
                    price=price,
                    reason='测试买入'
                )
            else:
                # 更新持仓价格（模拟市值变化）
                position = PositionModel.objects.get(account_id=self.account.account_id)
                position.current_price = price
                position.market_value = position.quantity * price
                position.unrealized_pnl = (price - float(position.avg_cost)) * position.quantity
                position.unrealized_pnl_pct = ((price - float(position.avg_cost)) / float(position.avg_cost)) * 100
                position.save()

                # 更新账户市值
                account_model = SimulatedAccountModel.objects.get(id=self.account.account_id)
                account_model.current_market_value = Decimal(str(position.market_value))
                account_model.total_value = account_model.current_cash + Decimal(str(position.market_value))
                account_model.save()

            # 记录每日净值
            self.net_value_service.record_and_update_performance(
                account_id=self.account.account_id,
                record_date=current_date
            )

        # 获取净值曲线
        equity_curve = self.net_value_service.get_equity_curve(self.account.account_id)

        # 验证记录数
        self.assertEqual(len(equity_curve), len(price_sequence))

        # 验证净值 = 现金 + 市值
        for point in equity_curve:
            self.assertAlmostEqual(
                point['net_value'],
                point['cash'] + point['market_value'],
                places=2,
                msg="净值必须等于现金加持仓市值"
            )

        # 验证总收益率 - 账户的 total_return 是基于 initial_capital 计算的
        updated_account = self.account_repo.get_by_id(self.account.account_id)
        expected_total_return = ((float(updated_account.total_value) - float(updated_account.initial_capital)) / float(updated_account.initial_capital)) * 100
        self.assertAlmostEqual(updated_account.total_return, expected_total_return, places=2)

    def test_max_drawdown_calculation(self):
        """测试最大回撤计算"""
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        trade_date = date.today()

        # 创建先涨后跌的价格序列
        price_sequence = [10.00, 12.00, 15.00, 12.00, 11.00, 13.00]

        for i, price in enumerate(price_sequence):
            current_date = trade_date + timedelta(days=i)

            if i == 0:
                buy_use_case.execute(
                    account_id=self.account.account_id,
                    asset_code='000001.SZ',
                    asset_name='平安银行',
                    asset_type='equity',
                    quantity=1000,
                    price=price,
                    reason='测试买入'
                )
            else:
                position = PositionModel.objects.get(account_id=self.account.account_id)
                position.current_price = price
                position.market_value = position.quantity * price
                position.unrealized_pnl = (price - float(position.avg_cost)) * position.quantity
                position.unrealized_pnl_pct = ((price - float(position.avg_cost)) / float(position.avg_cost)) * 100
                position.save()

                account_model = SimulatedAccountModel.objects.get(id=self.account.account_id)
                account_model.current_market_value = position.market_value
                account_model.total_value = account_model.current_cash + Decimal(str(position.market_value))
                account_model.save()

            self.net_value_service.record_and_update_performance(
                account_id=self.account.account_id,
                record_date=current_date
            )

        # 获取净值曲线并验证最大回撤
        equity_curve = self.net_value_service.get_equity_curve(self.account.account_id)

        # 手动计算时序最大回撤
        peak_so_far = equity_curve[0]['net_value']
        max_drawdown = 0.0
        for point in equity_curve:
            if point['net_value'] > peak_so_far:
                peak_so_far = point['net_value']
            drawdown = ((peak_so_far - point['net_value']) / peak_so_far * 100) if peak_so_far > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        # 验证账户的最大回撤指标
        updated_account = self.account_repo.get_by_id(self.account.account_id)
        self.assertAlmostEqual(updated_account.max_drawdown, max_drawdown, places=1)

    def test_auto_trading_engine_calls_performance_update(self):
        """测试自动交易引擎调用绩效更新"""
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

        performance_use_case = GetAccountPerformanceUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        # 创建引擎（使用 Mock MarketDataProvider）
        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=buy_use_case,
            sell_use_case=sell_use_case,
            performance_use_case=performance_use_case,
            market_data_provider=MockMarketDataProvider(
                prices={"000001.SZ": 10.50}
            )
        )

        trade_date = date.today()

        # 执行自动交易
        engine.run_daily_trading(trade_date)

        # 验证净值记录已创建
        net_value_exists = DailyNetValueModel.objects.filter(
            account_id=self.account.account_id,
            record_date=trade_date
        ).exists()

        # 如果有交易，应该有净值记录
        trades_count = SimulatedTradeModel.objects.filter(
            account_id=self.account.account_id,
            execution_date=trade_date
        ).count()

        if trades_count > 0:
            self.assertTrue(net_value_exists, "有交易时应该创建净值记录")
            net_value_record = DailyNetValueModel.objects.get(
                account_id=self.account.account_id,
                record_date=trade_date
            )
            # 验证净值 = 现金 + 市值
            self.assertAlmostEqual(
                float(net_value_record.net_value),
                float(net_value_record.cash + net_value_record.market_value),
                places=2
            )

    def test_daily_return_calculation(self):
        """测试日收益率计算"""
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        day1 = date.today()

        # 第一天买入
        buy_use_case.execute(
            account_id=self.account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
            reason='测试买入'
        )
        self.net_value_service.record_and_update_performance(
            account_id=self.account.account_id,
            record_date=day1
        )

        # 第二天价格上涨
        day2 = day1 + timedelta(days=1)
        position = PositionModel.objects.get(account_id=self.account.account_id)
        position.current_price = 11.00  # 涨10%
        position.market_value = position.quantity * position.current_price
        position.unrealized_pnl = (float(position.current_price) - float(position.avg_cost)) * position.quantity
        position.unrealized_pnl_pct = ((float(position.current_price) - float(position.avg_cost)) / float(position.avg_cost)) * 100
        position.save()

        account_model = SimulatedAccountModel.objects.get(id=self.account.account_id)
        account_model.current_market_value = Decimal(str(position.market_value))
        account_model.total_value = account_model.current_cash + Decimal(str(position.market_value))
        account_model.save()

        self.net_value_service.record_and_update_performance(
            account_id=self.account.account_id,
            record_date=day2
        )

        # 获取两天的净值记录
        nv1 = DailyNetValueModel.objects.get(account_id=self.account.account_id, record_date=day1)
        nv2 = DailyNetValueModel.objects.get(account_id=self.account.account_id, record_date=day2)

        # 验证日收益率
        expected_daily_return = ((float(nv2.net_value) - float(nv1.net_value)) / float(nv1.net_value)) * 100
        self.assertAlmostEqual(nv2.daily_return, expected_daily_return, places=2)

    def test_drawdown_field_accuracy(self):
        """测试回撤字段准确性"""
        buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

        trade_date = date.today()

        # 创建先涨后跌序列
        price_sequence = [10.00, 15.00, 12.00, 10.00]

        for i, price in enumerate(price_sequence):
            current_date = trade_date + timedelta(days=i)

            if i == 0:
                buy_use_case.execute(
                    account_id=self.account.account_id,
                    asset_code='000001.SZ',
                    asset_name='平安银行',
                    asset_type='equity',
                    quantity=1000,
                    price=price,
                    reason='测试买入'
                )
            else:
                position = PositionModel.objects.get(account_id=self.account.account_id)
                position.current_price = price
                position.market_value = position.quantity * price
                position.unrealized_pnl = (price - float(position.avg_cost)) * position.quantity
                position.unrealized_pnl_pct = ((price - float(position.avg_cost)) / float(position.avg_cost)) * 100
                position.save()

                account_model = SimulatedAccountModel.objects.get(id=self.account.account_id)
                account_model.current_market_value = position.market_value
                account_model.total_value = account_model.current_cash + Decimal(str(position.market_value))
                account_model.save()

            self.net_value_service.record_and_update_performance(
                account_id=self.account.account_id,
                record_date=current_date
            )

        # 获取净值曲线
        equity_curve = self.net_value_service.get_equity_curve(self.account.account_id)

        # 验证每个点的回撤字段
        peak_so_far = equity_curve[0]['net_value']
        for point in equity_curve:
            current_value = point['net_value']
            if current_value > peak_so_far:
                peak_so_far = current_value

            # 计算预期回撤
            expected_drawdown = ((peak_so_far - current_value) / peak_so_far * 100) if peak_so_far > 0 else 0

            # 验证回撤字段
            self.assertAlmostEqual(point['drawdown'], expected_drawdown, places=1)
