"""
多维度筛选 API 集成测试

测试 POST /api/asset-analysis/multidim-screen/ 端点
"""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.asset_analysis.infrastructure.models import WeightConfigModel
from apps.fund.infrastructure.models import FundInfoModel
from apps.regime.infrastructure.models import RegimeLog

User = get_user_model()


@pytest.mark.django_db
class TestMultiDimScreenAPI(TestCase):
    """多维度筛选 API 测试"""

    def setUp(self):
        """设置测试数据（每个测试前执行）"""
        self.client = APIClient()

        # 创建或获取测试用户并强制认证
        self.user, _ = User.objects.get_or_create(
            username='testuser',
            defaults={
                'password': 'testpass123'
            }
        )
        self.client.force_authenticate(user=self.user)

        # 创建权重配置
        WeightConfigModel.objects.get_or_create(
            name="default",
            defaults={
                "description": "默认权重配置",
                "regime_weight": 0.40,
                "policy_weight": 0.25,
                "sentiment_weight": 0.20,
                "signal_weight": 0.15,
                "is_active": True,
                "priority": 0,
            }
        )

        # 创建测试基金数据
        FundInfoModel.objects.get_or_create(
            fund_code="110011",
            defaults={
                "fund_name": "易方达优质精选混合",
                "fund_type": "混合型",
                "investment_style": "成长",
                "management_company": "易方达基金",
                "fund_scale": 50_000_000_000,  # 500亿
                "is_active": True,
            }
        )

        # 创建测试 Regime 数据
        RegimeLog.objects.get_or_create(
            observed_at=date.today(),
            defaults={
                "growth_momentum_z": 1.5,
                "inflation_momentum_z": 0.5,
                "distribution": {"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
                "dominant_regime": "Recovery",
                "confidence": 0.85,
            }
        )

    def test_multidim_screen_no_501(self):
        """确认不再返回 501"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {},
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        # 验证不再返回 501
        self.assertNotEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)

    def test_multidim_screen_fund_success(self):
        """测试多维度筛选 - 基金（成功）"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {"fund_type": "混合型"},
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        # 不再返回 501
        self.assertNotEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)

        # 检查响应结构
        self.assertIn("success", response.data)
        self.assertIn("timestamp", response.data)
        self.assertIn("context", response.data)
        self.assertIn("weights", response.data)
        self.assertIn("assets", response.data)

    def test_multidim_screen_with_custom_weights(self):
        """测试多维度筛选 - 自定义权重"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {},
            "weights": {
                "regime": 0.50,
                "policy": 0.20,
                "sentiment": 0.15,
                "signal": 0.15,
            },
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertNotEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
        self.assertIn("success", response.data)

    def test_multidim_screen_with_context_override(self):
        """测试多维度筛选 - 覆盖上下文"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {},
            "regime": "Overheat",
            "policy_level": "P2",
            "sentiment_index": -1.5,
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertNotEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)

        # 检查上下文是否被覆盖
        context = response.data.get("context", {})
        self.assertEqual(context.get("regime"), "Overheat")
        self.assertEqual(context.get("policy_level"), "P2")
        self.assertEqual(context.get("sentiment_index"), -1.5)

    def test_multidim_screen_invalid_asset_type(self):
        """测试多维度筛选 - 无效的资产类型"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "invalid_type",
            "filters": {},
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("success", response.data)
        self.assertFalse(response.data["success"])

    def test_multidim_screen_invalid_weights(self):
        """测试多维度筛选 - 无效的权重"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {},
            "weights": {
                "regime": 0.50,
                "policy": 0.20,
                "sentiment": 0.15,
                "signal": 0.10,  # 总和不为 1.0
            },
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("success", response.data)
        self.assertFalse(response.data["success"])

    def test_multidim_screen_response_fields_align_with_screen_asset_type(self):
        """测试 multidim-screen 响应字段与 screen/{asset_type} 对齐"""
        url = reverse("api_asset_analysis:multidim_screen")
        data = {
            "asset_type": "fund",
            "filters": {},
            "max_count": 10,
        }

        response = self.client.post(url, data, format="json")

        self.assertNotEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)

        # 检查响应字段是否对齐
        expected_fields = {
            "success",
            "timestamp",
            "context",
            "weights",
            "assets",
            "message",  # 可选
        }
        actual_fields = set(response.data.keys())
        self.assertTrue(expected_fields.issubset(actual_fields))

        # 检查 assets 列表中的字段
        assets = response.data.get("assets", [])
        for asset in assets:
            expected_asset_fields = {
                "asset_code",
                "asset_name",
                "asset_type",
                "scores",
                "total_score",
                "rank",
                "allocation",
                "risk_level",
            }
            actual_asset_fields = set(asset.keys())
            self.assertTrue(expected_asset_fields.issubset(actual_asset_fields))

            # 检查 scores 字段
            scores = asset.get("scores", {})
            expected_score_fields = {
                "regime",
                "policy",
                "sentiment",
                "signal",
                "custom",
                "total",
            }
            actual_score_fields = set(scores.keys())
            self.assertTrue(expected_score_fields.issubset(actual_score_fields))
