"""
Fund Module Integration Tests

集成测试：测试基金数据持久化和基本数据流。
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.test import TestCase

from apps.fund.infrastructure.models import (
    FundHoldingModel,
    FundInfoModel,
    FundManagerModel,
    FundNetValueModel,
    FundPerformanceModel,
    FundSectorAllocationModel,
)


@pytest.mark.django_db
class TestFundDataPersistence(TestCase):
    """测试基金数据持久化"""

    def setUp(self):
        """设置测试数据"""
        self.fund1 = FundInfoModel.objects.create(
            fund_code='000001',
            fund_name='华夏成长',
            management_company='华夏基金',
            fund_type='混合型',
            investment_style='成长',
            setup_date='2001-12-18',
            fund_scale=Decimal('3236832400.00'),
        )

        self.fund2 = FundInfoModel.objects.create(
            fund_code='000002',
            fund_name='华夏回报',
            management_company='华夏基金',
            fund_type='混合型',
            investment_style='价值',
            setup_date='2003-09-05',
            fund_scale=Decimal('3797000000.00'),
        )

    def test_fund_info_persistence(self):
        """测试基金信息持久化"""
        self.assertEqual(FundInfoModel.objects.count(), 2)
        fund1 = FundInfoModel.objects.get(fund_code='000001')
        self.assertEqual(fund1.fund_name, '华夏成长')
        self.assertEqual(fund1.investment_style, '成长')

    def test_fund_manager_persistence(self):
        """测试基金经理数据持久化"""
        FundManagerModel.objects.create(
            fund_code=self.fund1.fund_code,
            manager_name='张三',
            tenure_start='2020-01-01',
        )

        self.assertEqual(
            FundManagerModel.objects.filter(fund_code='000001').count(),
            1
        )

    def test_net_value_persistence(self):
        """测试净值数据持久化"""
        base_date = date.today() - timedelta(days=10)
        for i in range(10):
            FundNetValueModel.objects.create(
                fund_code=self.fund1.fund_code,
                nav_date=base_date + timedelta(days=i),
                unit_nav=Decimal('1.0') + Decimal(i * 0.01),
                accum_nav=Decimal('1.0') + Decimal(i * 0.01) + Decimal('0.5'),
                daily_return=0.5,
            )

        self.assertEqual(
            FundNetValueModel.objects.filter(fund_code='000001').count(),
            10
        )

    def test_holdings_persistence(self):
        """测试持仓数据持久化"""
        FundHoldingModel.objects.create(
            fund_code=self.fund1.fund_code,
            report_date=date.today() - timedelta(days=30),
            stock_code='000001',
            stock_name='平安银行',
            holding_amount=1000000,
            holding_value=Decimal('10000000'),
            holding_ratio=5.2,
        )

        holding = FundHoldingModel.objects.get(fund_code='000001')
        self.assertEqual(holding.stock_code, '000001')

    def test_sector_allocation_persistence(self):
        """测试行业配置数据持久化"""
        FundSectorAllocationModel.objects.create(
            fund_code=self.fund1.fund_code,
            report_date=date.today() - timedelta(days=30),
            sector_name='金融',
            allocation_ratio=25.5,
        )

        allocation = FundSectorAllocationModel.objects.get(fund_code='000001')
        self.assertEqual(allocation.sector_name, '金融')

    def test_performance_persistence(self):
        """测试业绩数据持久化"""
        start_date = date.today() - timedelta(days=365)
        FundPerformanceModel.objects.create(
            fund_code=self.fund1.fund_code,
            start_date=start_date,
            end_date=date.today(),
            total_return=25.5,
            annualized_return=22.0,
            volatility=15.5,
            max_drawdown=-18.5,
            sharpe_ratio=1.45,
        )

        perf = FundPerformanceModel.objects.get(fund_code='000001')
        self.assertEqual(perf.total_return, 25.5)


@pytest.mark.django_db
class TestFundRelationships(TestCase):
    """测试基金表关系"""

    def setUp(self):
        """设置测试数据"""
        self.fund = FundInfoModel.objects.create(
            fund_code='000003',
            fund_name='易方达蓝筹',
            management_company='易方达基金',
            fund_type='混合型',
            investment_style='价值',
        )

    def test_fund_manager_relationship(self):
        """测试基金与经理关系"""
        # 创建多个经理
        FundManagerModel.objects.create(
            fund_code=self.fund.fund_code,
            manager_name='李四',
            tenure_start='2020-01-01',
            tenure_end='2022-12-31',
        )
        FundManagerModel.objects.create(
            fund_code=self.fund.fund_code,
            manager_name='王五',
            tenure_start='2023-01-01',
        )

        manager_count = FundManagerModel.objects.filter(
            fund_code='000003'
        ).count()
        self.assertEqual(manager_count, 2)

    def test_fund_net_value_relationship(self):
        """测试基金与净值关系"""
        # 创建净值序列
        for i in range(20):
            FundNetValueModel.objects.create(
                fund_code=self.fund.fund_code,
                nav_date=date.today() - timedelta(days=19-i),
                unit_nav=Decimal('1.0') + Decimal(i * 0.01),
                accum_nav=Decimal('1.0') + Decimal(i * 0.01) + Decimal('0.5'),
                daily_return=0.5,
            )

        nav_count = FundNetValueModel.objects.filter(
            fund_code='000003'
        ).count()
        self.assertEqual(nav_count, 20)


@pytest.mark.django_db
class TestFundConstraints(TestCase):
    """测试约束条件"""

    def test_fund_code_unique(self):
        """测试基金代码唯一性"""
        FundInfoModel.objects.create(
            fund_code='000010',
            fund_name='测试基金1',
            management_company='测试公司',
            fund_type='股票型',
        )

        # 重复代码应该失败
        with self.assertRaises(IntegrityError):
            FundInfoModel.objects.create(
                fund_code='000010',
                fund_name='测试基金2',
                management_company='测试公司',
                fund_type='股票型',
            )

    def test_nav_unique_constraint(self):
        """测试净值数据唯一约束"""
        fund = FundInfoModel.objects.create(
            fund_code='000011',
            fund_name='测试基金',
            management_company='测试公司',
            fund_type='股票型',
        )

        nav_date = date.today()

        # 第一条应该成功
        FundNetValueModel.objects.create(
            fund_code=fund.fund_code,
            nav_date=nav_date,
            unit_nav=Decimal('1.5'),
            accum_nav=Decimal('2.0'),
            daily_return=0.5,
        )

        # 重复应该失败（unique_together 约束）
        with self.assertRaises(IntegrityError):
            FundNetValueModel.objects.create(
                fund_code=fund.fund_code,
                nav_date=nav_date,
                unit_nav=Decimal('1.6'),
                accum_nav=Decimal('2.1'),
                daily_return=0.6,
            )
