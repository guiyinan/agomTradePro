"""
Asset Name Resolver - 资产名称解析服务测试

测试资产代码到名称的解析功能。
数据来源是数据库表，不是硬编码或mock。
"""

import os
from datetime import datetime, timezone

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
django.setup()

from django.test import TestCase
from django.core.cache import cache

from apps.asset_analysis.application.asset_name_service import (
    AssetNameResolver,
    enrich_with_asset_names,
    resolve_asset_name,
    resolve_asset_names,
)


class AssetNameResolverTest(TestCase):
    """资产名称解析器测试"""

    def setUp(self):
        """准备测试数据"""
        from apps.equity.infrastructure.models import StockInfoModel
        from apps.fund.infrastructure.models import FundHoldingModel
        from apps.fund.infrastructure.models import FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        cache.clear()
        StockInfoModel.objects.all().delete()
        FundHoldingModel.objects.all().delete()
        FundInfoModel.objects.all().delete()
        AssetClassModel.objects.all().delete()

        StockInfoModel.objects.create(
            stock_code="000001.SZ",
            name="平安银行",
            sector="银行",
            market="SZ",
            list_date="1991-04-03",
        )
        StockInfoModel.objects.create(
            stock_code="000333.SZ",
            name="美的集团",
            sector="家电",
            market="SZ",
            list_date="2013-09-18",
        )
        StockInfoModel.objects.create(
            stock_code="000651.SZ",
            name="格力电器",
            sector="家电",
            market="SZ",
            list_date="1991-06-25",
        )

        FundInfoModel.objects.create(
            fund_code="510300",
            fund_name="沪深300ETF",
            fund_type="指数型",
        )
        FundInfoModel.objects.create(
            fund_code="159915",
            fund_name="易方达创业板ETF",
            fund_type="指数型",
        )
        FundInfoModel.objects.create(
            fund_code="110011",
            fund_name="易方达深证100ETF",
            fund_type="指数型",
        )

        AssetClassModel.objects.create(
            code="510300",
            name="沪深300ETF",
            category="equity",
            description="跟踪沪深300指数",
            currency="CNY",
            is_active=True,
        )

        FundHoldingModel.objects.create(
            fund_code="510300",
            report_date="2025-12-31",
            stock_code="300308.SZ",
            stock_name="中际旭创",
            holding_amount=100,
            holding_value="100000.00",
            holding_ratio=1.2,
        )

    def tearDown(self):
        """清理测试数据"""
        from apps.equity.infrastructure.models import StockInfoModel
        from apps.fund.infrastructure.models import FundHoldingModel
        from apps.fund.infrastructure.models import FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        cache.clear()
        StockInfoModel.objects.all().delete()
        FundHoldingModel.objects.all().delete()
        FundInfoModel.objects.all().delete()
        AssetClassModel.objects.all().delete()

    def test_resolve_stock_names(self):
        """测试解析股票名称"""
        resolver = AssetNameResolver()

        result = resolver.resolve_asset_names(["000001.SZ", "000333.SZ"])
        self.assertEqual(result.get("000001.SZ"), "平安银行")
        self.assertEqual(result.get("000333.SZ"), "美的集团")
        self.assertNotIn("000651.SZ", result)

    def test_resolve_fund_names(self):
        """测试解析基金名称"""
        resolver = AssetNameResolver()

        result = resolver.resolve_asset_names(["510300.OF", "159915.OF", "110011.OF"])
        self.assertEqual(result.get("510300.OF"), "沪深300ETF")
        self.assertEqual(result.get("159915.OF"), "易方达创业板ETF")
        self.assertEqual(result.get("110011.OF"), "易方达深证100ETF")

    def test_resolve_mixed_codes(self):
        """测试解析混合代码"""
        resolver = AssetNameResolver()

        codes = ["000001.SZ", "510300.OF"]
        result = resolver.resolve_asset_names(codes)
        self.assertEqual(result.get("000001.SZ"), "平安银行")
        self.assertEqual(result.get("510300.OF"), "沪深300ETF")

    def test_resolve_rotation_asset_names_when_fund_info_missing(self):
        """测试 FundInfo 缺失时仍可从 rotation 资产表解析 ETF 名称。"""
        from apps.fund.infrastructure.models import FundInfoModel

        FundInfoModel.objects.filter(fund_code="510300").delete()
        cache.clear()

        resolver = AssetNameResolver()
        result = resolver.resolve_asset_names(["510300", "510300.SH"])

        self.assertEqual(result.get("510300"), "沪深300ETF")
        self.assertEqual(result.get("510300.SH"), "沪深300ETF")

    def test_resolve_stock_names_from_fund_holdings_when_stock_info_missing(self):
        """测试 StockInfo 缺失时仍可从基金持仓表回填成分股名称。"""
        from apps.equity.infrastructure.models import StockInfoModel

        StockInfoModel.objects.filter(stock_code="300308.SZ").delete()
        cache.clear()

        resolver = AssetNameResolver()
        result = resolver.resolve_asset_names(["300308.SZ"])

        self.assertEqual(result.get("300308.SZ"), "中际旭创")

    def test_resolve_single_code(self):
        """测试解析单个代码"""
        resolver = AssetNameResolver()

        result = resolver.resolve_asset_names(["000001.SZ"])
        self.assertEqual(result.get("000001.SZ"), "平安银行")

    def test_empty_codes(self):
        """测试空代码列表"""
        resolver = AssetNameResolver()

        result = resolver.resolve_asset_names([])
        self.assertEqual(result, {})

        result = resolver.resolve_asset_names([""])
        self.assertEqual(result, {})

        result = resolver.resolve_asset_names([None])
        self.assertEqual(result, {})

    def test_enrich_with_asset_names(self):
        """测试批量添加资产名称"""
        items = [
            {"asset_code": "000001.SZ", "other_field": "value1"},
            {"asset_code": "000333.SZ", "other_field": "value2"},
        ]
        result = enrich_with_asset_names(items)

        self.assertEqual(result[0]["asset_name"], "平安银行")
        self.assertEqual(result[1]["asset_name"], "美的集团")

    def test_resolve_asset_name_single(self):
        """测试 resolve_asset_name 单个代码解析"""
        # 直接使用类实例，避免缓存装饰器
        resolver = AssetNameResolver()
        result = resolver.resolve_asset_name("000001.SZ")
        self.assertEqual(result, "平安银行")

        resolver = AssetNameResolver()
        result = resolver.resolve_asset_name("NOTEXIST.XX")
        self.assertEqual(result, "NOTEXIST.XX")
