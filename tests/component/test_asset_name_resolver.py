"""
Asset Name Resolver - 资产名称解析服务测试

测试资产代码到名称的解析功能。
名称数据来源是本地数据库表，单元测试会隔离远程补全请求。
"""

import os
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
django.setup()

from django.core.cache import cache
from django.test import TestCase

from apps.asset_analysis.application.asset_name_service import (
    AssetNameResolver,
    enrich_with_asset_names,
    resolve_asset_names_read_only,
)


class AssetNameResolverTest(TestCase):
    """资产名称解析器测试"""

    def setUp(self):
        """准备测试数据"""
        from apps.data_center.infrastructure.models import AssetMasterModel
        from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        cache.clear()
        self.remote_name_patcher = patch(
            "apps.data_center.infrastructure.asset_master_backfill."
            "AssetMasterBackfillService._fetch_remote_name",
            return_value="",
        )
        self.remote_name_patcher.start()
        self.addCleanup(self.remote_name_patcher.stop)
        AssetMasterModel.objects.all().delete()
        FundHoldingModel.objects.all().delete()
        FundInfoModel.objects.all().delete()
        AssetClassModel.objects.all().delete()

        AssetMasterModel.objects.create(
            code="000001.SZ",
            name="平安银行",
            short_name="平安银行",
            asset_type="stock",
            exchange="SZSE",
            sector="银行",
            list_date="1991-04-03",
        )
        AssetMasterModel.objects.create(
            code="000333.SZ",
            name="美的集团",
            short_name="美的集团",
            asset_type="stock",
            exchange="SZSE",
            sector="家电",
            list_date="2013-09-18",
        )
        AssetMasterModel.objects.create(
            code="000651.SZ",
            name="格力电器",
            short_name="格力电器",
            asset_type="stock",
            exchange="SZSE",
            sector="家电",
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
        from apps.data_center.infrastructure.models import AssetMasterModel
        from apps.fund.infrastructure.models import FundHoldingModel, FundInfoModel
        from apps.rotation.infrastructure.models import AssetClassModel

        cache.clear()
        AssetMasterModel.objects.all().delete()
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
        cache.clear()

        resolver = AssetNameResolver()
        result = resolver.resolve_asset_names(["300308.SZ"])

        self.assertEqual(result.get("300308.SZ"), "中际旭创")

    def test_resolve_stock_names_from_data_center_when_stock_info_missing(self):
        """测试 StockInfo 缺失时从 data_center 资产主数据回填股票名称。"""
        from apps.data_center.infrastructure.models import AssetMasterModel
        AssetMasterModel.objects.create(
            code="600025.SH",
            name="华能水电",
            short_name="华能水电",
            asset_type="stock",
            exchange="SSE",
            is_active=True,
        )
        cache.clear()

        resolver = AssetNameResolver()
        result = resolver.resolve_asset_names(["600025.SH"])

        self.assertEqual(result.get("600025.SH"), "华能水电")

    def test_resolve_single_code(self):
        """测试解析单个代码"""
        resolver = AssetNameResolver()

        result = resolver.resolve_asset_names(["000001.SZ"])
        self.assertEqual(result.get("000001.SZ"), "平安银行")

    def test_read_only_resolution_does_not_populate_cache(self):
        """只读解析允许查库，但不得在 cache miss 时回写缓存。"""

        with patch("apps.asset_analysis.infrastructure.asset_name_resolver.cache.set") as cache_set:
            result = resolve_asset_names_read_only(["000001.SZ"])

        self.assertEqual(result.get("000001.SZ"), "平安银行")
        cache_set.assert_not_called()

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
