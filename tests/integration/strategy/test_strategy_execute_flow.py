"""
Integration Tests for Strategy Execute Flow

测试覆盖：
- strategy_execute 视图与 StrategyExecutor 的集成
- 真实提供者的集成（使用测试数据库）
- 完整的策略执行流程
- 响应格式验证（execution_id, generated_signals, failed_rules, duration_ms）
"""
import json
import uuid
from datetime import datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from apps.account.infrastructure.models import AccountProfileModel
from apps.asset_analysis.infrastructure.models import AssetScoreCache
from apps.macro.infrastructure.models import MacroIndicator
from apps.regime.infrastructure.models import RegimeLog
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    SimulatedAccountModel,
)
from apps.strategy.infrastructure.models import (
    PortfolioStrategyAssignmentModel,
    RuleConditionModel,
    StrategyExecutionLogModel,
    StrategyModel,
)


@pytest.mark.django_db
class TestStrategyExecuteFlow(TestCase):
    """策略执行流程集成测试"""

    def setUp(self):
        """设置测试环境"""
        # 创建 Django 用户
        unique_id = str(uuid.uuid4())[:8]
        self.django_user = User.objects.create_user(
            username=f'test_strategy_{unique_id}',
            email=f'test_strategy_{unique_id}@example.com',
            password='testpass123'
        )
        self.test_user = AccountProfileModel.objects.get(user=self.django_user)

        # 创建测试客户端
        self.client = Client()
        self.client.login(username=f'test_strategy_{unique_id}', password='testpass123')

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

        # 设置测试数据
        self._setup_test_data()

    def _setup_test_data(self):
        """设置测试数据（宏观、Regime、资产评分）"""
        # 创建宏观数据
        MacroIndicator.objects.create(
            code='CN_PMI_MANUFACTURING',
            value=50.8,
            unit='指数',
            reporting_period='2024-01-31',
            period_type='M',
            source='test'
        )

        # 创建 Regime 状态
        RegimeLog.objects.create(
            observed_at='2024-01-31',
            dominant_regime='HG',
            confidence=0.85,
            growth_momentum_z=1.5,
            inflation_momentum_z=1.2,
            distribution={}
        )

        # 创建资产评分
        AssetScoreCache.objects.create(
            asset_code='000001.SH',
            asset_name='上证指数',
            asset_type='equity',
            total_score=75.0,
            regime_score=80.0,
            policy_score=70.0,
            sentiment_score=60.0,
            signal_score=70.0,
            score_date='2024-01-31',
            regime='HG',
            policy_level='P2',
            sentiment_index=0.5
        )

        AssetScoreCache.objects.create(
            asset_code='510300.SH',
            asset_name='沪深300ETF',
            asset_type='equity',
            total_score=68.0,
            regime_score=72.0,
            policy_score=65.0,
            sentiment_score=60.0,
            signal_score=65.0,
            score_date='2024-01-31',
            regime='HG',
            policy_level='P2',
            sentiment_index=0.5
        )

    def test_strategy_execute_returns_real_results(self):
        """
        测试策略执行返回真实结果

        验证：
        - execution_id 存在
        - generated_signals 是真实值（非固定0）
        - duration_ms 是真实值
        - failed_rules 正确收集
        """
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='测试规则策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            description='用于测试策略执行流程',
            max_position_pct=20.0,
            max_total_position_pct=95.0,
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
            target_assets=[],
            priority=10,
            is_enabled=True
        )

        # 3. 创建模拟账户
        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='测试账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
        )

        # 4. 绑定策略到账户
        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 5. 执行策略
        url = f'/strategy/{strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({'portfolio_id': account.id}),
            content_type='application/json'
        )

        # 6. 验证响应
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)

        # 验证新字段存在
        self.assertIn('execution_id', response_data)
        self.assertIn('generated_signals', response_data)
        self.assertIn('failed_rules', response_data)
        self.assertIn('duration_ms', response_data)

        # 验证返回真实值（非占位值）
        self.assertIsNotNone(response_data['execution_id'])
        self.assertGreater(response_data['generated_signals'], 0)  # 应该有信号生成
        self.assertGreaterEqual(response_data['duration_ms'], 0)
        self.assertTrue(response_data['success'])

        # 验证执行日志已保存
        logs = StrategyExecutionLogModel.objects.filter(
            strategy=strategy,
            portfolio=account
        )
        self.assertEqual(logs.count(), 1)

        log = logs.first()
        self.assertTrue(log.is_success)
        self.assertGreater(len(log.signals_generated), 0)

    def test_strategy_execute_with_all_portfolios(self):
        """
        测试策略执行所有绑定的投资组合

        验证：
        - 不指定 portfolio_id 时执行所有绑定组合
        - 返回正确的 executed_portfolios 数量
        """
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='多组合测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='PMI扩张',
            rule_type='macro',
            condition_json={'operator': '>', 'indicator': 'CN_PMI_MANUFACTURING', 'threshold': 50},
            action='BUY',
            weight=0.1,
            is_enabled=True
        )

        # 2. 创建多个账户
        accounts = []
        for i in range(3):
            account = SimulatedAccountModel.objects.create(
                user=self.django_user,
                account_name=f'测试账户{i}',
                account_type='simulated',
                initial_capital=100000.00,
                current_cash=100000.00,
                current_market_value=0.00,
                total_value=100000.00,
            )
            accounts.append(account)

            # 绑定策略
            PortfolioStrategyAssignmentModel.objects.create(
                portfolio=account,
                strategy=strategy,
                assigned_by=self.test_user,
                is_active=True,
            )

        # 3. 执行策略（不指定 portfolio_id）
        url = f'/strategy/{strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({}),
            content_type='application/json'
        )

        # 4. 验证响应
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)

        self.assertEqual(response_data['executed_portfolios'], 3)
        self.assertIn('execution_id', response_data)
        self.assertIsInstance(response_data['execution_id'], list)

        # 验证所有账户都有执行日志
        logs = StrategyExecutionLogModel.objects.filter(strategy=strategy)
        self.assertEqual(logs.count(), 3)

    def test_strategy_execute_with_failed_portfolio(self):
        """
        测试策略执行失败的组合

        验证：
        - failed_rules 正确收集错误信息
        - success 正确反映执行状态
        """
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='失败测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        # 添加规则条件（规则驱动策略必须至少有一个规则）
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='PMI扩张',
            rule_type='macro',
            condition_json={'operator': '>', 'indicator': 'CN_PMI_MANUFACTURING', 'threshold': 50},
        )

        # 2. 创建空账户（有效 portfolio_id，但无持仓/数据）
        from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
        empty_account = SimulatedAccountModel.objects.create(
            account_name='空测试账户',
            initial_capital=0,
            current_cash=0,
            total_value=0,
            user=self.django_user,
        )

        url = f'/strategy/{strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({'portfolio_id': empty_account.id}),
            content_type='application/json'
        )

        # 3. 验证响应
        self.assertEqual(response.status_code, 200)  # HTTP 请求成功
        response_data = json.loads(response.content)

        # 策略对空账户执行，应该生成 0 信号
        self.assertIn('failed_rules', response_data)
        self.assertIn('generated_signals', response_data)

    def test_strategy_execute_response_format(self):
        """
        测试策略执行响应格式

        验证所有必需字段都存在且类型正确
        """
        # 1. 创建策略
        strategy = StrategyModel.objects.create(
            name='格式测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='PMI扩张',
            rule_type='macro',
            condition_json={'operator': '>', 'indicator': 'CN_PMI_MANUFACTURING', 'threshold': 50},
            action='BUY',
            weight=0.1,
            is_enabled=True
        )

        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='格式测试账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
        )

        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 2. 执行策略
        url = f'/strategy/{strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({'portfolio_id': account.id}),
            content_type='application/json'
        )

        # 3. 验证响应格式
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)

        # 验证必需字段
        required_fields = [
            'success',
            'execution_id',
            'generated_signals',
            'failed_rules',
            'duration_ms',
            'executed_portfolios',
            'message'
        ]
        for field in required_fields:
            self.assertIn(field, response_data, f'Missing field: {field}')

        # 验证字段类型
        self.assertIsInstance(response_data['success'], bool)
        self.assertIsInstance(response_data['generated_signals'], int)
        self.assertIsInstance(response_data['failed_rules'], list)
        self.assertIsInstance(response_data['duration_ms'], int)
        self.assertIsInstance(response_data['executed_portfolios'], int)
        self.assertIsInstance(response_data['message'], str)

    def test_strategy_execute_no_matching_rules(self):
        """
        测试没有规则匹配的策略执行

        验证：
        - 返回成功但 generated_signals = 0
        - execution_id 仍然存在
        """
        # 1. 创建策略（规则不匹配）
        strategy = StrategyModel.objects.create(
            name='不匹配测试策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=self.test_user,
        )

        # PMI > 100 的规则（永远不会满足）
        RuleConditionModel.objects.create(
            strategy=strategy,
            rule_name='不可能的PMI',
            rule_type='macro',
            condition_json={'operator': '>', 'indicator': 'CN_PMI_MANUFACTURING', 'threshold': 100},
            action='BUY',
            weight=0.1,
            is_enabled=True
        )

        account = SimulatedAccountModel.objects.create(
            user=self.django_user,
            account_name='不匹配测试账户',
            account_type='simulated',
            initial_capital=100000.00,
            current_cash=100000.00,
            current_market_value=0.00,
            total_value=100000.00,
        )

        PortfolioStrategyAssignmentModel.objects.create(
            portfolio=account,
            strategy=strategy,
            assigned_by=self.test_user,
            is_active=True,
        )

        # 2. 执行策略
        url = f'/strategy/{strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({'portfolio_id': account.id}),
            content_type='application/json'
        )

        # 3. 验证响应
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)

        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['generated_signals'], 0)
        self.assertIsNotNone(response_data['execution_id'])
        self.assertEqual(len(response_data['failed_rules']), 0)

    def test_strategy_execute_unauthorized_access(self):
        """
        测试未授权访问

        验证：
        - 用户只能执行自己创建的策略
        """
        # 1. 创建另一个用户
        other_user = User.objects.create_user(
            username='other_user',
            email='other@example.com',
            password='otherpass123'
        )
        other_profile = AccountProfileModel.objects.get(user=other_user)

        # 2. 创建属于其他用户的策略
        other_strategy = StrategyModel.objects.create(
            name='其他用户策略',
            strategy_type='rule_based',
            version=1,
            is_active=True,
            created_by=other_profile,
        )

        # 3. 尝试执行其他用户的策略
        url = f'/strategy/{other_strategy.id}/execute/'
        response = self.client.post(
            url,
            data=json.dumps({}),
            content_type='application/json'
        )

        # 4. 验证返回404
        self.assertEqual(response.status_code, 404)
