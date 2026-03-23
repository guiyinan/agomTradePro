"""
统一推荐 DTO 单元测试

测试 Application 层 DTO 的创建和转换。
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from apps.decision_rhythm.application.dtos import (
    UnifiedRecommendationDTO,
    RefreshRecommendationsRequestDTO,
    RefreshRecommendationsResponseDTO,
    ConflictDTO,
    RecommendationsListDTO,
    ConflictsListDTO,
    ExecutionPreviewDTO,
    ApproveExecutionRequestDTO,
    RejectExecutionRequestDTO,
    ExecutionResponseDTO,
)
from apps.decision_rhythm.domain.entities import (
    UnifiedRecommendation,
    RecommendationStatus,
    UserDecisionAction,
)


class TestUnifiedRecommendationDTO:
    """测试统一推荐 DTO"""

    def test_create_dto(self):
        """测试创建 DTO"""
        dto = UnifiedRecommendationDTO(
            recommendation_id="urec_test001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            composite_score=0.82,
            confidence=0.85,
        )

        assert dto.recommendation_id == "urec_test001"
        assert dto.account_id == "account_001"
        assert dto.security_code == "000001.SZ"
        assert dto.side == "BUY"
        assert dto.composite_score == 0.82

    def test_from_domain(self):
        """测试从 Domain 实体创建"""
        domain = UnifiedRecommendation(
            recommendation_id="urec_test001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            regime="GROWTH_INFLATION",
            regime_confidence=0.85,
            policy_level="LEVEL_2",
            beta_gate_passed=True,
            sentiment_score=0.72,
            flow_score=0.65,
            technical_score=0.78,
            fundamental_score=0.81,
            alpha_model_score=0.88,
            composite_score=0.82,
            confidence=0.85,
            reason_codes=["ALPHA_HIGH", "REGIME_FAVORABLE"],
            human_rationale="Alpha 分数高且 Regime 有利",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            entry_price_high=Decimal("15.20"),
            target_price_low=Decimal("18.00"),
            target_price_high=Decimal("20.00"),
            stop_loss_price=Decimal("13.50"),
            position_pct=5.0,
            suggested_quantity=1000,
            max_capital=Decimal("50000"),
            source_signal_ids=["sig_001"],
            source_candidate_ids=["cand_001"],
            feature_snapshot_id="fsn_001",
            status=RecommendationStatus.NEW,
            user_action=UserDecisionAction.WATCHING,
            user_action_note="来自首页 Alpha 推荐",
            user_action_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        dto = UnifiedRecommendationDTO.from_domain(domain)

        assert dto.recommendation_id == "urec_test001"
        assert dto.account_id == "account_001"
        assert dto.security_code == "000001.SZ"
        assert dto.side == "BUY"
        assert dto.regime == "GROWTH_INFLATION"
        assert dto.regime_confidence == 0.85
        assert dto.beta_gate_passed is True
        assert dto.composite_score == 0.82
        assert dto.confidence == 0.85
        assert "ALPHA_HIGH" in dto.reason_codes
        assert dto.status == "NEW"
        assert dto.user_action == "WATCHING"
        assert dto.user_action_note == "来自首页 Alpha 推荐"

    def test_to_dict(self):
        """测试转换为字典"""
        dto = UnifiedRecommendationDTO(
            recommendation_id="urec_test001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            created_at=datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc),
        )

        result = dto.to_dict()

        assert result["recommendation_id"] == "urec_test001"
        assert result["account_id"] == "account_001"
        assert result["security_code"] == "000001.SZ"
        assert result["side"] == "BUY"
        assert result["fair_value"] == "15.50"
        assert result["entry_price_low"] == "14.80"
        assert result["created_at"] == "2026-03-02T12:00:00+00:00"
        assert result["user_action"] == "PENDING"


class TestRefreshRecommendationsRequestDTO:
    """测试刷新推荐请求 DTO"""

    def test_create_dto(self):
        """测试创建 DTO"""
        dto = RefreshRecommendationsRequestDTO(
            account_id="account_001",
            security_codes=["000001.SZ", "000002.SZ"],
            force=True,
            async_mode=False,
        )

        assert dto.account_id == "account_001"
        assert dto.security_codes == ["000001.SZ", "000002.SZ"]
        assert dto.force is True
        assert dto.async_mode is False

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "account_id": "account_001",
            "security_codes": ["000001.SZ"],
            "force": True,
        }

        dto = RefreshRecommendationsRequestDTO.from_dict(data)

        assert dto.account_id == "account_001"
        assert dto.security_codes == ["000001.SZ"]
        assert dto.force is True
        assert dto.async_mode is True  # 默认值

    def test_default_values(self):
        """测试默认值"""
        dto = RefreshRecommendationsRequestDTO()

        assert dto.account_id is None
        assert dto.security_codes is None
        assert dto.force is False
        assert dto.async_mode is True


class TestRefreshRecommendationsResponseDTO:
    """测试刷新推荐响应 DTO"""

    def test_to_dict(self):
        """测试转换为字典"""
        dto = RefreshRecommendationsResponseDTO(
            task_id="task_001",
            status="RUNNING",
            message="正在刷新推荐",
            recommendations_count=10,
            conflicts_count=2,
        )

        result = dto.to_dict()

        assert result["task_id"] == "task_001"
        assert result["status"] == "RUNNING"
        assert result["message"] == "正在刷新推荐"
        assert result["recommendations_count"] == 10
        assert result["conflicts_count"] == 2


class TestConflictDTO:
    """测试冲突对象 DTO"""

    def test_to_dict(self):
        """测试转换为字典"""
        buy_rec = UnifiedRecommendationDTO(
            recommendation_id="urec_buy001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
        )
        sell_rec = UnifiedRecommendationDTO(
            recommendation_id="urec_sell001",
            account_id="account_001",
            security_code="000001.SZ",
            side="SELL",
        )

        dto = ConflictDTO(
            security_code="000001.SZ",
            account_id="account_001",
            buy_recommendation=buy_rec,
            sell_recommendation=sell_rec,
            conflict_type="BUY_SELL_CONFLICT",
            resolution_hint="需要人工判断方向",
        )

        result = dto.to_dict()

        assert result["security_code"] == "000001.SZ"
        assert result["account_id"] == "account_001"
        assert result["buy_recommendation"]["recommendation_id"] == "urec_buy001"
        assert result["sell_recommendation"]["recommendation_id"] == "urec_sell001"
        assert result["conflict_type"] == "BUY_SELL_CONFLICT"
        assert result["resolution_hint"] == "需要人工判断方向"


class TestRecommendationsListDTO:
    """测试推荐列表 DTO"""

    def test_to_dict(self):
        """测试转换为字典"""
        rec1 = UnifiedRecommendationDTO(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
        )
        rec2 = UnifiedRecommendationDTO(
            recommendation_id="urec_002",
            account_id="account_001",
            security_code="000002.SZ",
            side="BUY",
        )

        dto = RecommendationsListDTO(
            recommendations=[rec1, rec2],
            total_count=2,
            page=1,
            page_size=20,
        )

        result = dto.to_dict()

        assert len(result["recommendations"]) == 2
        assert result["total_count"] == 2
        assert result["page"] == 1
        assert result["page_size"] == 20


class TestConflictsListDTO:
    """测试冲突列表 DTO"""

    def test_to_dict(self):
        """测试转换为字典"""
        conflict1 = ConflictDTO(
            security_code="000001.SZ",
            account_id="account_001",
        )

        dto = ConflictsListDTO(
            conflicts=[conflict1],
            total_count=1,
        )

        result = dto.to_dict()

        assert len(result["conflicts"]) == 1
        assert result["total_count"] == 1


class TestExecutionPreviewDTO:
    """测试执行预览 DTO"""

    def test_to_dict(self):
        """测试转换为字典"""
        dto = ExecutionPreviewDTO(
            recommendation_id="urec_001",
            security_code="000001.SZ",
            side="BUY",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            entry_price_high=Decimal("15.20"),
            target_price_low=Decimal("18.00"),
            target_price_high=Decimal("20.00"),
            stop_loss_price=Decimal("13.50"),
            position_pct=5.0,
            suggested_quantity=1000,
            max_capital=Decimal("50000"),
            risk_check_results={"beta_check": "PASS", "regime_check": "PASS"},
            approval_request_id="apr_001",
        )

        result = dto.to_dict()

        assert result["recommendation_id"] == "urec_001"
        assert result["security_code"] == "000001.SZ"
        assert result["side"] == "BUY"
        assert result["fair_value"] == "15.50"
        assert result["risk_check_results"]["beta_check"] == "PASS"


class TestApproveExecutionRequestDTO:
    """测试批准执行请求 DTO"""

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "approval_request_id": "apr_001",
            "reviewer_comments": "同意执行",
            "execution_params": {"limit_price": 15.0},
        }

        dto = ApproveExecutionRequestDTO.from_dict(data)

        assert dto.approval_request_id == "apr_001"
        assert dto.reviewer_comments == "同意执行"
        assert dto.execution_params == {"limit_price": 15.0}


class TestRejectExecutionRequestDTO:
    """测试拒绝执行请求 DTO"""

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "approval_request_id": "apr_001",
            "reviewer_comments": "风险过高，拒绝执行",
        }

        dto = RejectExecutionRequestDTO.from_dict(data)

        assert dto.approval_request_id == "apr_001"
        assert dto.reviewer_comments == "风险过高，拒绝执行"


class TestExecutionResponseDTO:
    """测试执行响应 DTO"""

    def test_to_dict_success(self):
        """测试成功响应转换为字典"""
        dto = ExecutionResponseDTO(
            success=True,
            message="执行成功",
            execution_ref={"trade_id": "trade_001"},
            executed_at=datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc),
        )

        result = dto.to_dict()

        assert result["success"] is True
        assert result["message"] == "执行成功"
        assert result["execution_ref"]["trade_id"] == "trade_001"
        assert result["executed_at"] == "2026-03-02T12:00:00+00:00"

    def test_to_dict_failure(self):
        """测试失败响应转换为字典"""
        dto = ExecutionResponseDTO(
            success=False,
            message="执行失败：余额不足",
        )

        result = dto.to_dict()

        assert result["success"] is False
        assert result["message"] == "执行失败：余额不足"
        assert result["execution_ref"] is None
