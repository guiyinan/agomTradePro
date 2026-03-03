"""
统一推荐 API 契约测试

测试 API 端点的 Content-Type 和状态码。
"""

import pytest
from django.test import Client
from django.contrib.auth.models import User

from apps.decision_rhythm.infrastructure.models import (
    UnifiedRecommendationModel,
    DecisionModelParamConfigModel,
)


@pytest.fixture
def authenticated_client():
    """创建已认证的客户端"""
    user = User.objects.create_user(username="testuser", password="testpass")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
class TestUnifiedRecommendationsAPI:
    """测试统一推荐 API"""

    def test_recommendations_list_requires_account_id(self, authenticated_client):
        """测试推荐列表需要 account_id"""
        response = authenticated_client.get("/api/decision/workspace/recommendations/")

        assert response.status_code == 400
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["success"] is False
        assert "account_id" in data["error"].lower()

    def test_recommendations_list_empty(self, authenticated_client):
        """测试推荐列表为空"""
        response = authenticated_client.get("/api/decision/workspace/recommendations/?account_id=account_001")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "recommendations" in data["data"]
        assert data["data"]["total_count"] == 0

    def test_recommendations_list_with_data(self, authenticated_client):
        """测试推荐列表有数据"""
        # 创建测试数据
        UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            composite_score=0.8,
            confidence=0.85,
        )

        response = authenticated_client.get("/api/decision/workspace/recommendations/?account_id=account_001")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total_count"] == 1
        assert len(data["data"]["recommendations"]) == 1

    def test_recommendations_list_excludes_conflicts(self, authenticated_client):
        """测试推荐列表排除冲突"""
        # 创建正常推荐
        UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            composite_score=0.8,
            status="NEW",
        )
        # 创建冲突推荐
        UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_002",
            account_id="account_001",
            security_code="000002.SZ",
            side="BUY",
            composite_score=0.7,
            status="CONFLICT",
        )

        response = authenticated_client.get("/api/decision/workspace/recommendations/?account_id=account_001")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["total_count"] == 1
        assert data["data"]["recommendations"][0]["recommendation_id"] == "urec_001"

    def test_recommendations_list_pagination(self, authenticated_client):
        """测试推荐列表分页"""
        # 创建多条数据
        for i in range(25):
            UnifiedRecommendationModel.objects.create(
                recommendation_id=f"urec_{i:03d}",
                account_id="account_001",
                security_code=f"00000{i:02d}.SZ",
                side="BUY",
                composite_score=0.8 - i * 0.01,
            )

        response = authenticated_client.get("/api/decision/workspace/recommendations/?account_id=account_001&page=2&page_size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["page"] == 2
        assert data["data"]["page_size"] == 10
        assert len(data["data"]["recommendations"]) == 10


@pytest.mark.django_db
class TestRefreshRecommendationsAPI:
    """测试刷新推荐 API"""

    def test_refresh_recommendations_post(self, authenticated_client):
        """测试刷新推荐 POST"""
        response = authenticated_client.post(
            "/api/decision/workspace/recommendations/refresh/",
            data={"account_id": "account_001"},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "task_id" in data["data"]

    def test_refresh_recommendations_accepts_empty_body(self, authenticated_client):
        """测试刷新推荐接受空请求体"""
        response = authenticated_client.post(
            "/api/decision/workspace/recommendations/refresh/",
            data={},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


@pytest.mark.django_db
class TestConflictsAPI:
    """测试冲突 API"""

    def test_conflicts_list_requires_account_id(self, authenticated_client):
        """测试冲突列表需要 account_id"""
        response = authenticated_client.get("/api/decision/workspace/conflicts/")

        assert response.status_code == 400
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["success"] is False

    def test_conflicts_list_empty(self, authenticated_client):
        """测试冲突列表为空"""
        response = authenticated_client.get("/api/decision/workspace/conflicts/?account_id=account_001")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total_count"] == 0

    def test_conflicts_list_with_data(self, authenticated_client):
        """测试冲突列表有数据"""
        # 创建冲突推荐
        UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_buy",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            status="CONFLICT",
        )
        UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_sell",
            account_id="account_001",
            security_code="000001.SZ",
            side="SELL",
            status="CONFLICT",
        )

        response = authenticated_client.get("/api/decision/workspace/conflicts/?account_id=account_001")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["total_count"] == 1  # 按 security_code 分组后只有一个冲突
        assert len(data["data"]["conflicts"]) == 1


@pytest.mark.django_db
class TestModelParamsAPI:
    """测试模型参数 API"""

    def test_params_list(self, authenticated_client):
        """测试参数列表"""
        # 创建测试参数
        DecisionModelParamConfigModel.objects.create(
            config_id="mpc_001",
            param_key="alpha_model_weight",
            param_value="0.40",
            param_type="float",
            env="dev",
            is_active=True,
        )

        response = authenticated_client.get("/api/decision/workspace/params/?env=dev")

        assert response.status_code == 200
        assert response["Content-Type"] == "application/json"
        data = response.json()
        assert data["success"] is True
        assert "data" in data
        assert "params" in data["data"]
        assert "alpha_model_weight" in data["data"]["params"]

    def test_params_update_requires_fields(self, authenticated_client):
        """测试参数更新需要必填字段"""
        response = authenticated_client.post(
            "/api/decision/workspace/params/update/",
            data={},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False

    def test_params_update_creates_new(self, authenticated_client):
        """测试参数更新创建新参数"""
        response = authenticated_client.post(
            "/api/decision/workspace/params/update/",
            data={
                "param_key": "test_param",
                "param_value": "0.5",
                "param_type": "float",
                "env": "dev",
                "updated_reason": "测试创建",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["param_key"] == "test_param"
        assert data["data"]["new_value"] == "0.5"

    def test_params_update_existing(self, authenticated_client):
        """测试参数更新现有参数"""
        # 创建现有参数
        DecisionModelParamConfigModel.objects.create(
            config_id="mpc_001",
            param_key="existing_param",
            param_value="0.30",
            param_type="float",
            env="dev",
            is_active=True,
            version=1,
        )

        response = authenticated_client.post(
            "/api/decision/workspace/params/update/",
            data={
                "param_key": "existing_param",
                "param_value": "0.45",
                "param_type": "float",
                "env": "dev",
                "updated_reason": "更新测试",
            },
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["old_value"] == "0.30"
        assert data["data"]["new_value"] == "0.45"
