"""
Equity Module Integration Tests

集成测试：测试数据持久化和基本数据流。
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.test import TestCase

from apps.equity.infrastructure.models import (
    FinancialDataModel,
    StockDailyModel,
    StockInfoModel,
    ValuationModel,
)
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
class TestEquityDataPersistence(TestCase):
    """测试数据持久化"""

    def setUp(self):
        """设置测试数据"""
        # 创建测试股票
        self.stock1 = StockInfoModel.objects.create(
            stock_code='000001',
            name='平安银行',
            sector='银行',
            market='SZ',
            list_date='1991-04-03',
        )

        self.stock2 = StockInfoModel.objects.create(
            stock_code='600000',
            name='浦发银行',
            sector='银行',
            market='SH',
            list_date='1999-11-10',
        )

    def test_stock_info_persistence(self):
        """测试股票信息持久化"""
        created_count = StockInfoModel.objects.filter(
            stock_code__in=["000001", "600000"]
        ).count()
        self.assertEqual(created_count, 2)
        stock1 = StockInfoModel.objects.get(stock_code='000001')
        self.assertEqual(stock1.name, '平安银行')
        self.assertEqual(stock1.sector, '银行')

    def test_daily_data_persistence(self):
        """测试日线数据持久化"""
        # 创建日线数据
        base_date = date.today() - timedelta(days=10)
        for i in range(10):
            current_date = base_date + timedelta(days=i)
            StockDailyModel.objects.create(
                stock_code=self.stock1.stock_code,
                trade_date=current_date,
                open=Decimal('10.0') + Decimal(i),
                high=Decimal('11.0') + Decimal(i),
                low=Decimal('9.5') + Decimal(i),
                close=Decimal('10.5') + Decimal(i),
                volume=1000000,
                amount=Decimal('10000000'),
            )

        self.assertEqual(
            StockDailyModel.objects.filter(stock_code='000001').count(),
            10
        )

    def test_financial_data_persistence(self):
        """测试财务数据持久化"""
        FinancialDataModel.objects.create(
            stock_code=self.stock1.stock_code,
            report_date=date.today() - timedelta(days=30),
            report_type='4Q',
            revenue=Decimal('100000000000'),
            net_profit=Decimal('50000000000'),
            total_assets=Decimal('1000000000000'),
            total_liabilities=Decimal('900000000000'),
            equity=Decimal('100000000000'),
            roe=15.5,
            debt_ratio=90.0,
        )

        self.assertEqual(
            FinancialDataModel.objects.filter(stock_code='000001').count(),
            1
        )

    def test_valuation_data_persistence(self):
        """测试估值数据持久化"""
        ValuationModel.objects.create(
            stock_code=self.stock1.stock_code,
            trade_date=date.today(),
            pe=15.5,
            pe_ttm=16.2,
            pb=1.2,
            ps=2.5,
            total_mv=Decimal('200000000000'),
            circ_mv=Decimal('150000000000'),
        )

        valuation = ValuationModel.objects.get(stock_code='000001')
        self.assertEqual(valuation.pe, 15.5)


@pytest.mark.django_db
class TestEquityRelationships(TestCase):
    """测试表关系"""

    def setUp(self):
        """设置测试数据"""
        self.stock = StockInfoModel.objects.create(
            stock_code='000002',
            name='万科A',
            sector='房地产',
            market='SZ',
            list_date='1991-01-29',
        )

    def test_stock_daily_relationship(self):
        """测试股票与日线数据关系"""
        # 创建多条日线数据
        for i in range(5):
            StockDailyModel.objects.create(
                stock_code=self.stock.stock_code,
                trade_date=date.today() - timedelta(days=i),
                open=Decimal('10.0'),
                high=Decimal('11.0'),
                low=Decimal('9.5'),
                close=Decimal('10.5'),
                volume=1000000,
                amount=Decimal('10000000'),
            )

        # 验证关系
        daily_count = StockDailyModel.objects.filter(
            stock_code=self.stock.stock_code
        ).count()
        self.assertEqual(daily_count, 5)

    def test_unique_constraint(self):
        """测试唯一约束"""
        trade_date = date.today()

        # 第一条应该成功
        StockDailyModel.objects.create(
            stock_code=self.stock.stock_code,
            trade_date=trade_date,
            open=Decimal('10.0'),
            high=Decimal('11.0'),
            low=Decimal('9.5'),
            close=Decimal('10.5'),
            volume=1000000,
            amount=Decimal('10000000'),
        )

        # 重复应该失败（unique_together 约束）
        with self.assertRaises(IntegrityError):
            StockDailyModel.objects.create(
                stock_code=self.stock.stock_code,
                trade_date=trade_date,
                open=Decimal('10.1'),
                high=Decimal('11.1'),
                low=Decimal('9.6'),
                close=Decimal('10.6'),
                volume=1000000,
                amount=Decimal('10000000'),
            )


@pytest.mark.django_db
class TestEquityRepository(TestCase):
    """测试 Repository 基本功能"""

    def setUp(self):
        """设置测试数据"""
        self.stock = StockInfoModel.objects.create(
            stock_code='000003',
            name='中国平安',
            sector='保险',
            market='SH',
            list_date='2007-03-01',
        )

    def test_repository_basic_query(self):
        """测试 Repository 基本查询"""
        repo = DjangoStockRepository()

        # 测试基本查询（假设Repository实现了这些方法）
        # 这里只验证Repository可以被实例化
        self.assertIsNotNone(repo)
