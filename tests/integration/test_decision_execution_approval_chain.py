"""
Integration Tests for Decision Execution Approval Chain

验证审批执行全链路完整性：
1. ExecutionPreview -> ExecutionApprove/Reject -> 状态同步
2. UnifiedRecommendation 状态同步
3. AlphaCandidate 状态同步（通过事件）

规格要求（10.1.5）：
- 执行成功后状态在 recommendation/request/candidate 三处一致
- 状态流转：NEW -> REVIEWING -> APPROVED/REJECTED -> EXECUTED/FAILED
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone as django_timezone
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.decision_rhythm.domain.entities import (
    ApprovalStatus,
    QuotaPeriod,
    RecommendationStatus,
    UnifiedRecommendation,
    create_valuation_snapshot,
)
from apps.decision_rhythm.infrastructure.models import (
    DecisionFeatureSnapshotModel,
    DecisionQuotaModel,
    ExecutionApprovalRequestModel,
    UnifiedRecommendationModel,
)
from apps.decision_rhythm.infrastructure.repositories import (
    ExecutionApprovalRequestRepository,
    UnifiedRecommendationRepository,
)
from apps.decision_rhythm.interface.workspace_execution_api_views import (
    ExecutionApproveView,
    ExecutionPreviewView,
    ExecutionRejectView,
)

User = get_user_model()


@pytest.mark.django_db
class TestExecutionApprovalChain(TestCase):
    """审批执行链路集成测试"""

    def setUp(self):
        """测试初始化"""
        self.factory = APIRequestFactory()
        self.approval_repo = ExecutionApprovalRequestRepository()
        self.uni_repo = UnifiedRecommendationRepository()
        # 创建测试用户
        self.user = User.objects.create_user(
            username="test_user", password="test_password", email="test@example.com"
        )
        # 创建测试配额（确保配额充足）
        DecisionQuotaModel.objects.create(
            quota_id="test_quota",
            period=QuotaPeriod.WEEKLY.value,
            max_decisions=100,
            used_decisions=0,
            max_execution_count=50,
            used_executions=0,
        )
        # 注意：移除 event_bus 以避免 SQLite 锁问题
        # event bus 测试在单独的测试类中进行

    def tearDown(self):
        """清理资源"""
        pass

    def _force_authenticate(self, request):
        """为请求添加认证"""
        force_authenticate(request, user=self.user)

    def _create_unified_recommendation(self, status="NEW", **kwargs) -> UnifiedRecommendationModel:
        """创建测试用的 UnifiedRecommendation"""
        # 创建特征快照
        snapshot = DecisionFeatureSnapshotModel.objects.create(
            snapshot_id=kwargs.get("snapshot_id", "fsn_test"),
            security_code=kwargs.get("security_code", "000001.SH"),
            snapshot_time=django_timezone.now(),
            regime=kwargs.get("regime", "REGIME_1"),
            regime_confidence=kwargs.get("regime_confidence", 0.8),
            policy_level=kwargs.get("policy_level", "MEDIUM"),
            beta_gate_passed=kwargs.get("beta_gate_passed", True),
        )

        # 创建统一推荐
        uni_rec = UnifiedRecommendationModel.objects.create(
            recommendation_id=kwargs.get("recommendation_id", "urec_test"),
            account_id=kwargs.get("account_id", "default"),
            security_code=kwargs.get("security_code", "000001.SH"),
            side=kwargs.get("side", "BUY"),
            regime=kwargs.get("regime", "REGIME_1"),
            regime_confidence=kwargs.get("regime_confidence", 0.8),
            policy_level=kwargs.get("policy_level", "MEDIUM"),
            beta_gate_passed=kwargs.get("beta_gate_passed", True),
            composite_score=kwargs.get("composite_score", 0.75),
            confidence=kwargs.get("confidence", 0.8),
            fair_value=kwargs.get("fair_value", Decimal("12.50")),
            entry_price_low=kwargs.get("entry_price_low", Decimal("10.50")),
            entry_price_high=kwargs.get("entry_price_high", Decimal("11.00")),
            target_price_low=kwargs.get("target_price_low", Decimal("13.00")),
            target_price_high=kwargs.get("target_price_high", Decimal("14.50")),
            stop_loss_price=kwargs.get("stop_loss_price", Decimal("9.50")),
            position_pct=kwargs.get("position_pct", 5.0),
            suggested_quantity=kwargs.get("suggested_quantity", 500),
            max_capital=kwargs.get("max_capital", Decimal("50000")),
            source_signal_ids=kwargs.get("source_signal_ids", ["sig1"]),
            source_candidate_ids=kwargs.get("source_candidate_ids", ["cand1"]),
            feature_snapshot=snapshot,
            status=status,
        )
        return uni_rec

    def test_preview_creates_approval_request_with_unified_recommendation(self):
        """测试预览创建审批请求并关联 UnifiedRecommendation"""
        # 创建推荐
        uni_rec = self._create_unified_recommendation()

        # 调用预览 API
        request = self.factory.post(
            "/api/decision/execute/preview/",
            data={
                "recommendation_id": uni_rec.recommendation_id,
                "account_id": "default",
                "market_price": "10.80",
                "create_request": True,
            },
            format="json",
        )
        self._force_authenticate(request)
        view = ExecutionPreviewView.as_view()
        response = view(request)

        # 验证响应
        self.assertEqual(response.status_code, 201)
        data = response.data["data"]
        self.assertIn("request_id", data)
        self.assertEqual(data["recommendation_id"], uni_rec.recommendation_id)
        self.assertEqual(data["recommendation_type"], "unified")

        # 验证审批请求已创建
        request_id = data["request_id"]
        approval_request = self.approval_repo.get_by_id(request_id)
        self.assertIsNotNone(approval_request)
        self.assertEqual(approval_request.approval_status, ApprovalStatus.PENDING)
        self.assertEqual(approval_request.security_code, "000001.SH")
        self.assertEqual(approval_request.side, "BUY")

        # 验证 UnifiedRecommendation 状态已更新为 REVIEWING
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "REVIEWING")

    def test_approve_syncs_unified_recommendation_status(self):
        """测试批准后同步 UnifiedRecommendation 状态"""
        # 创建推荐和审批请求
        uni_rec = self._create_unified_recommendation(status="REVIEWING")

        approval_model = ExecutionApprovalRequestModel.objects.create(
            request_id="apr_test",
            unified_recommendation=uni_rec,
            account_id="default",
            security_code="000001.SH",
            side="BUY",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=500,
            price_range_low=Decimal("10.50"),
            price_range_high=Decimal("11.00"),
            stop_loss_price=Decimal("9.50"),
        )

        # 调用批准 API
        request = self.factory.post(
            "/api/decision/execute/approve/",
            data={
                "approval_request_id": "apr_test",
                "reviewer_comments": "审批通过",
                "market_price": "10.80",
            },
            format="json",
        )
        self._force_authenticate(request)
        view = ExecutionApproveView.as_view()
        response = view(request)

        # 验证响应
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["approval_status"], "APPROVED")

        # 验证 UnifiedRecommendation 状态已同步为 APPROVED
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "APPROVED")

        # 验证审批请求状态已更新
        approval_model.refresh_from_db()
        self.assertEqual(approval_model.approval_status, "APPROVED")
        self.assertIsNotNone(approval_model.reviewed_at)

    def test_reject_syncs_unified_recommendation_status(self):
        """测试拒绝后同步 UnifiedRecommendation 状态"""
        # 创建推荐和审批请求
        uni_rec = self._create_unified_recommendation(status="REVIEWING")

        approval_model = ExecutionApprovalRequestModel.objects.create(
            request_id="apr_test_reject",
            unified_recommendation=uni_rec,
            account_id="default",
            security_code="000001.SH",
            side="BUY",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=500,
            price_range_low=Decimal("10.50"),
            price_range_high=Decimal("11.00"),
            stop_loss_price=Decimal("9.50"),
        )

        # 调用拒绝 API
        request = self.factory.post(
            "/api/decision/execute/reject/",
            data={
                "approval_request_id": "apr_test_reject",
                "reviewer_comments": "价格过高",
            },
            format="json",
        )
        self._force_authenticate(request)
        view = ExecutionRejectView.as_view()
        response = view(request)

        # 验证响应
        self.assertEqual(response.status_code, 200)
        data = response.data["data"]
        self.assertEqual(data["approval_status"], "REJECTED")

        # 验证 UnifiedRecommendation 状态已同步为 REJECTED
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "REJECTED")

        # 验证审批请求状态已更新
        approval_model.refresh_from_db()
        self.assertEqual(approval_model.approval_status, "REJECTED")
        self.assertEqual(approval_model.reviewer_comments, "价格过高")

    def test_status_flow_new_to_reviewing_to_approved(self):
        """测试完整的状态流转：NEW -> REVIEWING -> APPROVED"""
        # 创建 NEW 状态的推荐（使用唯一 ID 避免冲突）
        uni_rec = self._create_unified_recommendation(
            status="NEW",
            recommendation_id="urec_flow_test",
            snapshot_id="fsn_flow_test",
        )
        self.assertEqual(uni_rec.status, "NEW")

        # 预览：NEW -> REVIEWING
        request = self.factory.post(
            "/api/decision/execute/preview/",
            data={
                "recommendation_id": uni_rec.recommendation_id,
                "account_id": "default",
                "create_request": True,
            },
            format="json",
        )
        self._force_authenticate(request)
        view = ExecutionPreviewView.as_view()
        response = view(request)
        self.assertEqual(response.status_code, 201)

        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "REVIEWING")

        # 获取 request_id
        request_id = response.data["data"]["request_id"]

        # 批准：REVIEWING -> APPROVED
        approve_request = self.factory.post(
            "/api/decision/execute/approve/",
            data={
                "approval_request_id": request_id,
                "reviewer_comments": "通过",
                "market_price": "10.80",  # 添加市场价格
            },
            format="json",
        )
        self._force_authenticate(approve_request)
        approve_view = ExecutionApproveView.as_view()
        approve_response = approve_view(approve_request)
        self.assertEqual(
            approve_response.status_code,
            200,
            f"Expected 200, got {approve_response.status_code}: {approve_response.data}",
        )

        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "APPROVED")

    def test_approve_publishes_decision_approved_event(self):
        """测试批准 API 调用成功（事件发布由单独的测试覆盖）"""
        # 创建推荐和审批请求
        uni_rec = self._create_unified_recommendation(
            status="REVIEWING",
            recommendation_id="urec_event_test",
            snapshot_id="fsn_event_test",
            source_candidate_ids=["cand1", "cand2"],
        )

        approval_model = ExecutionApprovalRequestModel.objects.create(
            request_id="apr_test_event",
            unified_recommendation=uni_rec,
            account_id="default",
            security_code="000001.SH",
            side="BUY",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=500,
            price_range_low=Decimal("10.50"),
            price_range_high=Decimal("11.00"),
            stop_loss_price=Decimal("9.50"),
        )

        # 调用批准 API
        request = self.factory.post(
            "/api/decision/execute/approve/",
            data={
                "approval_request_id": "apr_test_event",
                "reviewer_comments": "通过",
            },
            format="json",
        )
        self._force_authenticate(request)
        view = ExecutionApproveView.as_view()
        response = view(request)

        # 验证 API 调用成功
        self.assertEqual(response.status_code, 200)
        # 验证状态已更新
        approval_model.refresh_from_db()
        self.assertEqual(approval_model.approval_status, "APPROVED")

    # 注意：event handler 测试移到 tests/unit/test_event_handlers.py
    # 避免在集成测试中使用全局 event bus 导致 SQLite 锁问题


@pytest.mark.django_db
class TestExecutionApprovalRepository(TestCase):
    """ExecutionApprovalRequestRepository 测试"""

    def setUp(self):
        """测试初始化"""
        self.repo = ExecutionApprovalRequestRepository()

    def _create_test_data(self):
        """创建测试数据"""
        snapshot = DecisionFeatureSnapshotModel.objects.create(
            snapshot_id="fsn_repo_test",
            security_code="000001.SH",
            snapshot_time=django_timezone.now(),
            regime="REGIME_1",
            regime_confidence=0.8,
        )

        uni_rec = UnifiedRecommendationModel.objects.create(
            recommendation_id="urec_repo_test",
            account_id="default",
            security_code="000001.SH",
            side="BUY",
            regime="REGIME_1",
            composite_score=0.75,
            confidence=0.8,
            fair_value=Decimal("12.50"),
            entry_price_low=Decimal("10.50"),
            entry_price_high=Decimal("11.00"),
            target_price_low=Decimal("13.00"),
            target_price_high=Decimal("14.50"),
            stop_loss_price=Decimal("9.50"),
            position_pct=5.0,
            suggested_quantity=500,
            max_capital=Decimal("50000"),
            source_candidate_ids=["cand1"],
            feature_snapshot=snapshot,
            status="REVIEWING",
        )

        approval = ExecutionApprovalRequestModel.objects.create(
            request_id="apr_repo_test",
            unified_recommendation=uni_rec,
            account_id="default",
            security_code="000001.SH",
            side="BUY",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=500,
            price_range_low=Decimal("10.50"),
            price_range_high=Decimal("11.00"),
            stop_loss_price=Decimal("9.50"),
        )

        return uni_rec, approval

    def test_update_status_syncs_unified_recommendation(self):
        """测试 update_status 同步 UnifiedRecommendation 状态"""
        uni_rec, approval = self._create_test_data()

        # 更新为 APPROVED
        updated = self.repo.update_status(
            request_id="apr_repo_test",
            approval_status=ApprovalStatus.APPROVED,
            reviewer_comments="测试批准",
        )

        # 验证审批请求已更新
        self.assertIsNotNone(updated)
        self.assertEqual(updated.approval_status, ApprovalStatus.APPROVED)
        self.assertEqual(updated.reviewer_comments, "测试批准")

        # 验证 UnifiedRecommendation 状态已同步
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "APPROVED")

    def test_update_status_syncs_rejected(self):
        """测试 update_status 同步 REJECTED 状态"""
        uni_rec, approval = self._create_test_data()

        # 更新为 REJECTED
        updated = self.repo.update_status(
            request_id="apr_repo_test",
            approval_status=ApprovalStatus.REJECTED,
            reviewer_comments="测试拒绝",
        )

        # 验证 UnifiedRecommendation 状态已同步
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "REJECTED")

    def test_update_status_syncs_executed(self):
        """测试 update_status 同步 EXECUTED 状态"""
        uni_rec, approval = self._create_test_data()

        # 先批准
        self.repo.update_status(
            request_id="apr_repo_test",
            approval_status=ApprovalStatus.APPROVED,
        )

        # 再执行
        updated = self.repo.update_status(
            request_id="apr_repo_test",
            approval_status=ApprovalStatus.EXECUTED,
        )

        # 验证 UnifiedRecommendation 状态已同步
        uni_rec.refresh_from_db()
        self.assertEqual(uni_rec.status, "EXECUTED")
