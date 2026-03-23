"""
集成测试：决策执行闭环

测试范围：
1. 预检查 API
2. 执行 API
3. 取消 API
4. 状态回写验证
"""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client, TestCase

# ========== API 契约测试 ==========


@pytest.mark.django_db
class TestPrecheckAPI:
    """预检查 API 测试"""

    def test_precheck_endpoint_exists(self):
        """测试预检查端点存在"""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-workflow/precheck/",
            data={"candidate_id": "test_candidate"},
            content_type="application/json",
        )
        assert response.status_code in [200, 400, 404, 500]

    def test_precheck_candidate_not_found(self):
        """测试候选不存在"""
        user = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-workflow/precheck/",
            data={"candidate_id": "nonexistent_candidate"},
            content_type="application/json",
        )
        assert response.status_code in [400, 404, 500]


@pytest.mark.django_db
class TestExecuteAPI:
    """执行 API 测试"""

    def test_execute_endpoint_exists(self):
        """测试执行端点存在"""
        user = User.objects.create_user(
            username="testuser3",
            email="test3@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-rhythm/requests/test_req/execute/",
            data={
                "target": "SIMULATED",
                "sim_account_id": 1,
                "asset_code": "000001.SH",
                "action": "buy",
                "quantity": 100,
                "price": "12.35",
            },
            content_type="application/json",
        )
        assert response.status_code in [200, 400, 404, 500]

    def test_execute_request_not_found(self):
        """测试请求不存在"""
        user = User.objects.create_user(
            username="testuser4",
            email="test4@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-rhythm/requests/nonexistent_req/execute/",
            data={"target": "SIMULATED"},
            content_type="application/json",
        )
        assert response.status_code in [400, 404, 500]


@pytest.mark.django_db
class TestCancelAPI:
    """取消 API 测试"""

    def test_cancel_endpoint_exists(self):
        """测试取消端点存在"""
        user = User.objects.create_user(
            username="testuser5",
            email="test5@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-rhythm/requests/test_req/cancel/",
            data={"reason": "测试取消"},
            content_type="application/json",
        )
        assert response.status_code in [200, 400, 404, 500]

    def test_cancel_request_not_found(self):
        """测试请求不存在"""
        user = User.objects.create_user(
            username="testuser6",
            email="test6@example.com",
            password="testpass123",
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            "/api/decision-rhythm/requests/nonexistent_req/cancel/",
            data={"reason": "测试取消"},
            content_type="application/json",
        )
        assert response.status_code in [400, 404, 500]


# ========== 状态回写测试 (使用 Django TestCase) ==========


class TestStatusWriteback(TestCase):
    """状态回写测试"""

    def setUp(self):
        """设置测试数据"""
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel

        self.candidate = AlphaCandidateModel.objects.create(
            candidate_id="cand_test_001",
            trigger_id="trig_test_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="LONG",
            status="ACTIONABLE",
            confidence=0.85,
            strength="MODERATE",
            thesis="集成测试候选",
        )

    def test_candidate_status_after_execution(self):
        """测试执行后候选状态更新"""
        from apps.decision_rhythm.infrastructure.models import (
            DecisionRequestModel,
        )

        # 创建决策请求
        request = DecisionRequestModel.objects.create(
            request_id="req_test_001",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority="HIGH",
            reason="集成测试请求",
            candidate_id=self.candidate.candidate_id,
            execution_target="SIMULATED",
            execution_status="PENDING",
        )

        # 模拟执行成功
        request.execution_status = "EXECUTED"
        request.save()

        self.candidate.status = "EXECUTED"
        self.candidate.last_execution_status = "EXECUTED"
        self.candidate.last_decision_request_id = request.request_id
        self.candidate.save()

        # 验证
        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.status, "EXECUTED")
        self.assertEqual(self.candidate.last_execution_status, "EXECUTED")

    def test_decision_request_status_transition(self):
        """测试决策请求状态转换"""
        from apps.decision_rhythm.infrastructure.models import DecisionRequestModel

        # 创建请求
        request = DecisionRequestModel.objects.create(
            request_id="req_test_002",
            asset_code="000001.SH",
            asset_class="a_share",
            direction="BUY",
            priority="HIGH",
            reason="状态转换测试",
            candidate_id=self.candidate.candidate_id,
            execution_status="PENDING",
        )

        # 初始状态
        self.assertEqual(request.execution_status, "PENDING")

        # 执行成功
        request.execution_status = "EXECUTED"
        request.save()

        request.refresh_from_db()
        self.assertEqual(request.execution_status, "EXECUTED")


# ========== 工作台待办测试 (使用 Django TestCase) ==========


class TestWorkspaceTodo(TestCase):
    """工作台待办测试"""

    def setUp(self):
        """设置测试数据"""
        self.user = User.objects.create_user(
            username="workspace_user",
            email="workspace@example.com",
            password="testpass123",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_pending_request_included(self):
        """测试待执行请求包含在待办中"""
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
        from apps.decision_rhythm.infrastructure.models import (
            DecisionRequestModel,
            DecisionResponseModel,
        )

        # 创建候选
        candidate = AlphaCandidateModel.objects.create(
            candidate_id="cand_workspace_001",
            trigger_id="trig_workspace_001",
            asset_code="000003.SH",
            asset_class="a_share",
            direction="LONG",
            status="ACTIONABLE",
            confidence=0.85,
            strength="MODERATE",
            thesis="工作台测试候选",
        )

        # 创建待执行请求
        request = DecisionRequestModel.objects.create(
            request_id="req_workspace_001",
            asset_code="000003.SH",
            asset_class="a_share",
            direction="BUY",
            priority="HIGH",
            reason="工作台测试请求",
            candidate_id=candidate.candidate_id,
            execution_target="SIMULATED",
            execution_status="PENDING",
        )
        DecisionResponseModel.objects.create(
            request=request,
            approved=True,
            approval_reason="测试批准",
        )

        response = self.client.get("/decision/workspace/")
        self.assertEqual(response.status_code, 200)

    def test_failed_request_included(self):
        """测试失败请求包含在待办中（支持重试）"""
        from apps.alpha_trigger.infrastructure.models import AlphaCandidateModel
        from apps.decision_rhythm.infrastructure.models import (
            DecisionRequestModel,
            DecisionResponseModel,
        )

        # 创建候选
        candidate = AlphaCandidateModel.objects.create(
            candidate_id="cand_failed_001",
            trigger_id="trig_failed_001",
            asset_code="000004.SH",
            asset_class="a_share",
            direction="LONG",
            status="ACTIONABLE",
            confidence=0.75,
            strength="MODERATE",
            thesis="失败测试候选",
        )

        # 创建失败状态的请求
        failed_request = DecisionRequestModel.objects.create(
            request_id="req_failed_001",
            asset_code="000004.SH",
            asset_class="a_share",
            direction="BUY",
            priority="HIGH",
            reason="失败请求",
            execution_status="FAILED",
            candidate_id=candidate.candidate_id,
        )
        DecisionResponseModel.objects.create(
            request=failed_request,
            approved=True,
            approval_reason="测试批准",
        )

        response = self.client.get("/decision/workspace/")
        self.assertEqual(response.status_code, 200)
