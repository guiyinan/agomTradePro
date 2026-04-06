"""
策略系统与自动交易引擎集成测试

Phase 5 端到端测试：
- 测试策略执行引擎与 AutoTradingEngine 的集成
- 测试规则策略的完整流程
- 测试向后兼容（无策略时使用原有逻辑）
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.use_cases import (
    CreateSimulatedAccountUseCase,
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
)
from apps.simulated_trading.domain.entities import SimulatedAccount
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.repositories import (
    DjangoPositionRepository,
    DjangoSimulatedAccountRepository,
    DjangoTradeRepository,
)
from apps.strategy.application.strategy_executor import StrategyExecutor
from apps.strategy.domain.entities import (
    ActionType,
    RuleCondition,
    SignalRecommendation,
    Strategy,
    StrategyExecutionResult,
    StrategyType,
)
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    RuleConditionModel,
    StrategyModel,
)


@pytest.mark.django_db
class TestStrategyAutoTradingIntegration(TestCase):
    """策略系统与自动交易引擎集成测试"""

    def setUp(self):
        """设置测试环境"""
        # 创建 Django 用户（信号会自动创建 AccountProfileModel）
        # 使用 UUID 确保唯一性
        unique_id = str(uuid.uuid4())[:8]

        self.django_user = User.objects.create_user(
            username=f'testuser_{unique_id}',
            email=f'test_{unique_id}@example.com'
        )
        # 获取信号自动创建的 AccountProfileModel
        self.test_user = AccountProfileModel.objects.get(user=self.django_user)

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

        # 创建用例
        self.create_account_use_case = CreateSimulatedAccountUseCase(self.account_repo)
        self.buy_use_case = ExecuteBuyOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )
        self.sell_use_case = ExecuteSellOrderUseCase(
            self.account_repo,
            self.position_repo,
            self.trade_repo
        )

    def test_account_without_strategy_uses_legacy_logic(self):
        """
        测试向后兼容：
        - 账户未绑定策略时，使用原有逻辑
        - 验证原有买入流程仍然正常工作
        """
        # 1. 创建未绑定策略的账户
        account = self.create_account_use_case.execute(
            account_name='未绑定策略账户',
            initial_capital=100000.00,
        )

        # 验证账户未绑定策略
        account_model = SimulatedAccountModel.objects.get(id=account.account_id)
        self.assertFalse(
            PortfolioStrategyAssignmentModel.objects.filter(
                portfolio=account_model,
                is_active=True
            ).exists()
        )

        # 2. 创建自动交易引擎（不传入 strategy_executor）
        price_provider = Mock()
        price_provider.get_price = Mock(return_value=10.50)

        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=self.buy_use_case,
            sell_use_case=self.sell_use_case,
            performance_use_case=Mock(),
            price_provider=price_provider,
            strategy_executor=None  # 未配置策略执行器
        )

        # 3. 处理账户（应该使用原有逻辑）
        buy_count, sell_count = engine._process_account(
            account=account,
            trade_date=date.today()
        )

        # 4. 验证原有逻辑正常工作
        # 由于没有买入候选，应该返回 0, 0
        self.assertEqual(buy_count, 0)
        self.assertEqual(sell_count, 0)

    def test_account_with_strategy_uses_strategy_executor(self):
        """
        测试策略系统集成：
        - 账户绑定策略后，使用策略执行引擎
        - 验证策略信号被正确执行
        """
        # 1. 创建测试策略
        strategy = StrategyModel.objects.create(
            name='测试规则策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            description='用于集成测试的规则策略',
            max_position_pct=20.0,
            max_total_position_pct=95.0,
            stop_loss_pct=10.0,
            created_by=self.test_user,
        )

        # 2. 创建规则条件（PMI > 50 时买入）
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='PMI扩张买入',
            rule_type='macro',
            condition_json={
                'operator': '>',
                'indicator': 'CN_PMI_MANUFACTURING',
                'threshold': 50
            },
            action='BUY',
            weight=0.15,
            target_assets=['000001.SZ'],
            priority=10,
            is_enabled=True
        )

        # 3. 创建绑定策略的账户
        account = self.create_account_use_case.execute(
            account_name='绑定策略账户',
            initial_capital=100000.00,
        )

        # 绑定策略到账户
        account_model = SimulatedAccountModel.objects.get(id=account.account_id)
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account_model,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 4. Mock 策略执行网关（engine 内部使用 gateway，不再直接使用 strategy_executor）
        from apps.strategy.application.execution_gateway import (
            ExecutionResult as GatewayExecutionResult,
        )
        from apps.strategy.application.execution_gateway import (
            SignalInfo,
        )

        mock_gateway = Mock()
        mock_gateway.execute_for_account.return_value = GatewayExecutionResult(
            success=True,
            signals=[
                SignalInfo(
                    signal_id=None,
                    asset_code='000001.SZ',
                    asset_name='平安银行',
                    action='buy',
                    quantity=1000,
                    confidence=0.85,
                    reason='PMI扩张（PMI=50.2 > 50）',
                )
            ],
        )
        # 网关还需提供 get_active_strategy_binding (facade 调用)
        mock_gateway.get_active_strategy_binding.return_value = {
            'strategy_id': strategy.id,
            'name': strategy.name,
            'strategy_type': 'rule_based',
            'is_active': True,
        }

        # 5. 创建自动交易引擎
        price_provider = Mock()
        price_provider.get_price = Mock(return_value=10.50)

        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=self.buy_use_case,
            sell_use_case=self.sell_use_case,
            performance_use_case=Mock(),
            price_provider=price_provider,
            strategy_executor=Mock(),  # 需要非 None 以触发策略路径
        )

        # 6. 处理账户（Patch 网关 — 覆盖 facade + engine 两处调用）
        with patch(
            'apps.strategy.application.execution_gateway.get_strategy_execution_gateway',
            return_value=mock_gateway,
        ):
            buy_count, sell_count = engine._process_account(
                account=account,
                trade_date=date.today()
            )

        # 7. 验证网关被调用
        mock_gateway.execute_for_account.assert_called_once()

        # 8. 验证买入信号被执行
        self.assertEqual(buy_count, 1)
        self.assertEqual(sell_count, 0)

        # 9. 验证持仓
        positions = self.position_repo.get_by_account(account.account_id)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].asset_code, '000001.SZ')
        self.assertEqual(positions[0].quantity, 1000)

    def test_strategy_executor_returns_sell_signal(self):
        """
        测试卖出信号执行：
        - 验证策略返回的卖出信号被正确执行
        """
        # 1. 创建测试策略
        strategy = StrategyModel.objects.create(
            name='测试卖出策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            description='用于测试卖出信号的策略',
            max_position_pct=20.0,
            created_by=self.test_user,
        )

        # 添加规则条件（规则驱动策略必须至少有一个规则）
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='PMI收缩卖出',
            rule_type='macro',
            condition_json={'operator': '<', 'indicator': 'CN_PMI_MANUFACTURING', 'threshold': 50},
        )

        # 2. 创建账户并绑定策略
        account = self.create_account_use_case.execute(
            account_name='卖出测试账户',
            initial_capital=100000.00,
        )

        account_model = SimulatedAccountModel.objects.get(id=account.account_id)
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account_model,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 3. 先创建一个持仓
        self.buy_use_case.execute(
            account_id=account.account_id,
            asset_code='000001.SZ',
            asset_name='平安银行',
            asset_type='equity',
            quantity=1000,
            price=10.00,
            reason='初始买入'
        )

        # 4. Mock 策略执行网关（返回卖出信号）
        from apps.strategy.application.execution_gateway import (
            ExecutionResult as GatewayExecutionResult,
        )
        from apps.strategy.application.execution_gateway import (
            SignalInfo,
        )

        mock_gateway = Mock()
        mock_gateway.execute_for_account.return_value = GatewayExecutionResult(
            success=True,
            signals=[
                SignalInfo(
                    signal_id=None,
                    asset_code='000001.SZ',
                    asset_name='平安银行',
                    action='sell',
                    quantity=None,  # 未指定数量，应该全部卖出
                    confidence=0.75,
                    reason='PMI收缩（PMI=49.5 < 50）',
                )
            ],
        )
        # 网关还需提供 get_active_strategy_binding (facade 调用)
        mock_gateway.get_active_strategy_binding.return_value = {
            'strategy_id': strategy.id,
            'name': strategy.name,
            'strategy_type': 'rule_based',
            'is_active': True,
        }

        # 5. 创建自动交易引擎
        price_provider = Mock()
        price_provider.get_price = Mock(return_value=11.00)

        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=self.buy_use_case,
            sell_use_case=self.sell_use_case,
            performance_use_case=Mock(),
            price_provider=price_provider,
            strategy_executor=Mock(),  # 需要非 None 以触发策略路径
        )

        # 6. 处理账户（Patch 网关）
        with patch(
            'apps.strategy.application.execution_gateway.get_strategy_execution_gateway',
            return_value=mock_gateway,
        ):
            buy_count, sell_count = engine._process_account(
                account=account,
                trade_date=date.today()
            )

        # 7. 验证卖出信号被执行
        self.assertEqual(buy_count, 0)
        self.assertEqual(sell_count, 1)

        # 8. 验证持仓已清空
        positions = self.position_repo.get_by_account(account.account_id)
        self.assertEqual(len(positions), 0)

    def test_get_account_strategy_id(self):
        """测试获取账户策略ID的方法"""
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        # 2. 创建未绑定策略的账户
        account1 = self.create_account_use_case.execute(
            account_name='未绑定策略',
            initial_capital=100000.00,
        )

        # 3. 创建绑定策略的账户
        account2 = self.create_account_use_case.execute(
            account_name='绑定策略',
            initial_capital=100000.00,
        )
        account_model2 = SimulatedAccountModel.objects.get(id=account2.account_id)
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account_model2,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 4. 创建引擎并测试
        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=self.buy_use_case,
            sell_use_case=self.sell_use_case,
            performance_use_case=Mock(),
        )

        # 5. 验证获取策略ID
        strategy_id_1 = engine._get_account_strategy_id(account1.account_id)
        self.assertIsNone(strategy_id_1)

        strategy_id_2 = engine._get_account_strategy_id(account2.account_id)
        self.assertEqual(strategy_id_2, strategy.id)

    def test_strategy_executor_failure_handling(self):
        """
        测试策略执行失败处理：
        - 验证策略执行失败时不会影响系统稳定性
        """
        # 1. 创建策略和账户
        strategy = StrategyModel.objects.create(
            name='失败测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        account = self.create_account_use_case.execute(
            account_name='失败测试账户',
            initial_capital=100000.00,
        )

        account_model = SimulatedAccountModel.objects.get(id=account.account_id)
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account_model,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 2. 创建 Mock 的策略执行器（模拟失败）
        mock_strategy_executor = Mock()
        mock_result = StrategyExecutionResult(
            strategy_id=strategy.id,
            portfolio_id=account.account_id,
            execution_time=datetime.now(),
            execution_duration_ms=100,
            signals=[],
            is_success=False,
            error_message='模拟策略执行失败',
            context={}
        )
        mock_strategy_executor.execute_strategy = Mock(return_value=mock_result)

        # 3. 创建自动交易引擎
        engine = AutoTradingEngine(
            account_repo=self.account_repo,
            position_repo=self.position_repo,
            trade_repo=self.trade_repo,
            buy_use_case=self.buy_use_case,
            sell_use_case=self.sell_use_case,
            performance_use_case=Mock(),
            strategy_executor=mock_strategy_executor
        )

        # 4. 处理账户（应该优雅处理失败）
        buy_count, sell_count = engine._process_account(
            account=account,
            trade_date=date.today()
        )

        # 5. 验证没有交易发生
        self.assertEqual(buy_count, 0)
        self.assertEqual(sell_count, 0)


@pytest.mark.django_db
class TestPortfolioStrategyAssignment(TestCase):
    """测试账户与策略关联表"""

    def setUp(self):
        """创建测试用户"""
        # 创建 Django 用户（信号会自动创建 AccountProfileModel）
        # 使用 UUID 确保唯一性
        unique_id = str(uuid.uuid4())[:8]

        self.django_user = User.objects.create_user(
            username=f'testuser_fk_{unique_id}',
            email=f'test_fk_{unique_id}@example.com'
        )
        # 获取信号自动创建的 AccountProfileModel
        self.test_user = AccountProfileModel.objects.get(user=self.django_user)

    def test_simulated_account_can_have_strategy(self):
        """测试 SimulatedAccount 可以通过关联表绑定 Strategy"""
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='测试策略',
            strategy_type='script_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        # 2. 创建账户并关联策略
        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='测试账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
            auto_trading_enabled=True,
        )
        assignment = PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 3. 验证关联
        self.assertEqual(assignment.strategy, strategy)
        self.assertEqual(assignment.strategy.name, '测试策略')

        # 4. 验证反向关联
        self.assertIn(assignment, strategy.portfolio_assignments.all())

    def test_strategy_assignment_optional(self):
        """测试账户可以不绑定策略"""
        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='无策略账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
        )

        self.assertFalse(
            PortfolioStrategyAssignmentModel.objects.filter(
                portfolio=account,
                is_active=True
            ).exists()
        )

    def test_strategy_delete_cascades_assignment(self):
        """测试策略删除时关联关系被级联删除"""
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='待删除策略',
            strategy_type='ai_driven',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        # 2. 创建账户并关联策略
        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='测试账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
        )
        assignment = PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        account_id = account.id
        self.assertTrue(
            PortfolioStrategyAssignmentModel.objects.filter(id=assignment.id).exists()
        )

        # 3. 删除策略
        strategy.delete()

        # 4. 验证关联被删除，账户仍存在
        self.assertFalse(
            PortfolioStrategyAssignmentModel.objects.filter(id=assignment.id).exists()
        )
        self.assertTrue(
            SimulatedAccountModel.objects.filter(id=account_id).exists()
        )
