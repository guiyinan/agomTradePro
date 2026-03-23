"""
Sector Module Integration Tests

集成测试：测试板块数据持久化和基本数据流。
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.test import TestCase

from apps.sector.infrastructure.models import (
    SectorConstituentModel,
    SectorIndexModel,
    SectorInfoModel,
    SectorRelativeStrengthModel,
)


@pytest.mark.django_db
class TestSectorDataPersistence(TestCase):
    """测试板块数据持久化"""

    def setUp(self):
        """设置测试数据"""
        self.sector1 = SectorInfoModel.objects.create(
            sector_code='801010',
            sector_name='银行',
            level='SW1',
            parent_code=None,
        )

        self.sector2 = SectorInfoModel.objects.create(
            sector_code='801020',
            sector_name='房地产',
            level='SW1',
            parent_code=None,
        )

    def test_sector_info_persistence(self):
        """测试板块信息持久化"""
        self.assertEqual(SectorInfoModel.objects.count(), 2)
        sector1 = SectorInfoModel.objects.get(sector_code='801010')
        self.assertEqual(sector1.sector_name, '银行')
        self.assertEqual(sector1.level, 'SW1')

    def test_sector_index_persistence(self):
        """测试板块指数数据持久化"""
        base_date = date.today() - timedelta(days=10)
        for i in range(10):
            SectorIndexModel.objects.create(
                sector_code=self.sector1.sector_code,
                trade_date=base_date + timedelta(days=i),
                open_price=Decimal('1000.0') + Decimal(i * 2),
                high=Decimal('1010.0') + Decimal(i * 2),
                low=Decimal('990.0') + Decimal(i * 2),
                close=Decimal('1005.0') + Decimal(i * 2),
                volume=100000000,
                amount=Decimal('1000000000'),
                change_pct=0.5,
            )

        self.assertEqual(
            SectorIndexModel.objects.filter(sector_code='801010').count(),
            10
        )

    def test_constituent_persistence(self):
        """测试成分股数据持久化"""
        SectorConstituentModel.objects.create(
            sector_code=self.sector1.sector_code,
            stock_code='000001',
            enter_date='2024-01-01',
        )

        self.assertEqual(
            SectorConstituentModel.objects.filter(sector_code='801010').count(),
            1
        )

    def test_relative_strength_persistence(self):
        """测试相对强弱数据持久化"""
        SectorRelativeStrengthModel.objects.create(
            sector_code=self.sector1.sector_code,
            trade_date=date.today(),
            relative_strength=0.8,
            momentum=15.5,
            momentum_window=20,
        )

        rs = SectorRelativeStrengthModel.objects.get(sector_code='801010')
        self.assertEqual(rs.relative_strength, 0.8)


@pytest.mark.django_db
class TestSectorRelationships(TestCase):
    """测试板块表关系"""

    def setUp(self):
        """设置测试数据"""
        # 创建一级行业
        self.parent_sector = SectorInfoModel.objects.create(
            sector_code='801010',
            sector_name='银行',
            level='SW1',
        )

        # 创建二级行业
        self.sub_sector = SectorInfoModel.objects.create(
            sector_code='801010.I01',
            sector_name='国有大行',
            parent_code='801010',
            level='SW2',
        )

    def test_sector_hierarchy(self):
        """测试板块层级关系"""
        children = SectorInfoModel.objects.filter(parent_code='801010')
        self.assertEqual(children.count(), 1)
        self.assertEqual(children.first().sector_name, '国有大行')

    def test_sector_index_relationship(self):
        """测试板块与指数数据关系"""
        for i in range(5):
            SectorIndexModel.objects.create(
                sector_code=self.parent_sector.sector_code,
                trade_date=date.today() - timedelta(days=i),
                open_price=Decimal('1000.0') + Decimal(i),
                high=Decimal('1010.0') + Decimal(i),
                low=Decimal('990.0') + Decimal(i),
                close=Decimal('1005.0') + Decimal(i),
                volume=100000000,
                amount=Decimal('1000000000'),
                change_pct=0.5,
            )

        index_count = SectorIndexModel.objects.filter(
            sector_code=self.parent_sector.sector_code
        ).count()
        self.assertEqual(index_count, 5)


@pytest.mark.django_db
class TestSectorConstraints(TestCase):
    """测试约束条件"""

    def test_sector_code_unique(self):
        """测试板块代码唯一性"""
        SectorInfoModel.objects.create(
            sector_code='801030',
            sector_name='医药生物',
            level='SW1',
        )

        # 重复代码应该失败
        with self.assertRaises(Exception):
            SectorInfoModel.objects.create(
                sector_code='801030',
                sector_name='医药生物2',
                level='SW1',
            )

    def test_index_unique_constraint(self):
        """测试指数数据唯一约束"""
        sector = SectorInfoModel.objects.create(
            sector_code='801040',
            sector_name='食品饮料',
            level='SW1',
        )

        trade_date = date.today()

        # 第一条应该成功
        SectorIndexModel.objects.create(
            sector_code=sector.sector_code,
            trade_date=trade_date,
            open_price=Decimal('1000.0'),
            high=Decimal('1010.0'),
            low=Decimal('990.0'),
            close=Decimal('1005.0'),
            volume=100000000,
            amount=Decimal('1000000000'),
            change_pct=0.5,
        )

        # 重复应该失败（unique_together 约束）
        with self.assertRaises(Exception):
            SectorIndexModel.objects.create(
                sector_code=sector.sector_code,
                trade_date=trade_date,
                open_price=Decimal('1001.0'),
                high=Decimal('1011.0'),
                low=Decimal('991.0'),
                close=Decimal('1006.0'),
                volume=100000000,
                amount=Decimal('1000000000'),
                change_pct=0.6,
            )
