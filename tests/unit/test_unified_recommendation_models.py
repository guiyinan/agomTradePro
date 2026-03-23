"""
统一推荐模型单元测试

测试 DecisionFeatureSnapshotModel、UnifiedRecommendationModel、
DecisionModelParamConfigModel、DecisionModelParamAuditLogModel 的创建和查询。
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from apps.decision_rhythm.infrastructure.models import (
    DecisionFeatureSnapshotModel,
    UnifiedRecommendationModel,
    DecisionModelParamConfigModel,
    DecisionModelParamAuditLogModel,
    DecisionRequestModel,
    ExecutionApprovalRequestModel,
    InvestmentRecommendationModel,
    ValuationSnapshotModel,
)
from apps.decision_rhythm.domain.entities import (
    RecommendationStatus,
    UserDecisionAction,
    DecisionPriority,
    ExecutionTarget,
    ExecutionStatus,
    ApprovalStatus,
)


@pytest.fixture
def feature_snapshot_data():
    """特征快照测试数据"""
    return {
        "snapshot_id": "fsn_test001",
        "security_code": "000001.SZ",
        "snapshot_time": datetime.now(timezone.utc),
        "regime": "GROWTH_INFLATION",
        "regime_confidence": 0.85,
        "policy_level": "LEVEL_2",
        "beta_gate_passed": True,
        "sentiment_score": 0.72,
        "flow_score": 0.65,
        "technical_score": 0.78,
        "fundamental_score": 0.81,
        "alpha_model_score": 0.88,
        "extra_features": {"market_cap": 5000000000, "pe_ratio": 15.5},
    }


@pytest.fixture
def unified_recommendation_data():
    """统一推荐测试数据"""
    return {
        "recommendation_id": "urec_test001",
        "account_id": "account_001",
        "security_code": "000001.SZ",
        "side": "BUY",
        "regime": "GROWTH_INFLATION",
        "regime_confidence": 0.85,
        "policy_level": "LEVEL_2",
        "beta_gate_passed": True,
        "sentiment_score": 0.72,
        "flow_score": 0.65,
        "technical_score": 0.78,
        "fundamental_score": 0.81,
        "alpha_model_score": 0.88,
        "composite_score": 0.82,
        "confidence": 0.85,
        "reason_codes": ["ALPHA_HIGH", "REGIME_FAVORABLE"],
        "human_rationale": "Alpha 分数高且 Regime 有利",
        "fair_value": Decimal("15.50"),
        "entry_price_low": Decimal("14.80"),
        "entry_price_high": Decimal("15.20"),
        "target_price_low": Decimal("18.00"),
        "target_price_high": Decimal("20.00"),
        "stop_loss_price": Decimal("13.50"),
        "position_pct": 5.0,
        "suggested_quantity": 1000,
        "max_capital": Decimal("50000"),
        "source_signal_ids": ["sig_001", "sig_002"],
        "source_candidate_ids": ["cand_001"],
        "status": RecommendationStatus.NEW.value,
    }


@pytest.mark.django_db
class TestDecisionFeatureSnapshotModel:
    """测试决策特征快照模型"""

    def test_create_feature_snapshot(self, feature_snapshot_data):
        """测试创建特征快照"""
        snapshot = DecisionFeatureSnapshotModel.objects.create(**feature_snapshot_data)

        assert snapshot.snapshot_id == feature_snapshot_data["snapshot_id"]
        assert snapshot.security_code == "000001.SZ"
        assert snapshot.regime == "GROWTH_INFLATION"
        assert snapshot.regime_confidence == 0.85
        assert snapshot.beta_gate_passed is True
        assert snapshot.sentiment_score == 0.72
        assert snapshot.alpha_model_score == 0.88
        assert snapshot.extra_features["market_cap"] == 5000000000

    def test_auto_generate_snapshot_id(self):
        """测试自动生成快照 ID"""
        snapshot = DecisionFeatureSnapshotModel.objects.create(
            security_code="000002.SZ",
            snapshot_time=datetime.now(timezone.utc),
        )
        assert snapshot.snapshot_id.startswith("fsn_")
        assert len(snapshot.snapshot_id) == 16

    def test_to_domain(self, feature_snapshot_data):
        """测试转换为 Domain 实体"""
        snapshot = DecisionFeatureSnapshotModel.objects.create(**feature_snapshot_data)
        domain = snapshot.to_domain()

        assert domain.snapshot_id == feature_snapshot_data["snapshot_id"]
        assert domain.security_code == "000001.SZ"
        assert domain.regime == "GROWTH_INFLATION"
        assert domain.regime_confidence == 0.85
        assert domain.beta_gate_passed is True

    def test_from_domain(self, feature_snapshot_data):
        """测试从 Domain 实体创建"""
        from apps.decision_rhythm.domain.entities import DecisionFeatureSnapshot

        domain = DecisionFeatureSnapshot(**feature_snapshot_data)
        model = DecisionFeatureSnapshotModel.from_domain(domain)

        assert model.snapshot_id == feature_snapshot_data["snapshot_id"]
        assert model.security_code == "000001.SZ"
        assert model.regime == "GROWTH_INFLATION"


@pytest.mark.django_db
class TestUnifiedRecommendationModel:
    """测试统一推荐模型"""

    def test_create_unified_recommendation(self, unified_recommendation_data):
        """测试创建统一推荐"""
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)

        assert recommendation.recommendation_id == "urec_test001"
        assert recommendation.account_id == "account_001"
        assert recommendation.security_code == "000001.SZ"
        assert recommendation.side == "BUY"
        assert recommendation.composite_score == 0.82
        assert recommendation.confidence == 0.85
        assert "ALPHA_HIGH" in recommendation.reason_codes
        assert recommendation.fair_value == Decimal("15.50")
        assert recommendation.status == RecommendationStatus.NEW.value
        assert recommendation.user_action == UserDecisionAction.PENDING.value

    def test_auto_generate_recommendation_id(self):
        """测试自动生成推荐 ID"""
        recommendation = UnifiedRecommendationModel.objects.create(
            account_id="account_001",
            security_code="000002.SZ",
            side="SELL",
        )
        assert recommendation.recommendation_id.startswith("urec_")
        assert len(recommendation.recommendation_id) == 17

    def test_aggregation_key(self, unified_recommendation_data):
        """测试聚合键"""
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)
        domain = recommendation.to_domain()

        assert domain.get_aggregation_key() == "account_001|000001.SZ|BUY"

    def test_is_executable(self, unified_recommendation_data):
        """测试是否可执行"""
        # NEW 状态，不可执行
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)
        domain = recommendation.to_domain()
        assert domain.is_executable() is False

        # APPROVED 状态且通过 Beta Gate，可执行
        recommendation.status = RecommendationStatus.APPROVED.value
        recommendation.save()
        domain = recommendation.to_domain()
        assert domain.is_executable() is True

        # APPROVED 状态但未通过 Beta Gate，不可执行
        recommendation.beta_gate_passed = False
        recommendation.save()
        domain = recommendation.to_domain()
        assert domain.is_executable() is False

    def test_to_domain(self, unified_recommendation_data):
        """测试转换为 Domain 实体"""
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)
        domain = recommendation.to_domain()

        assert domain.recommendation_id == "urec_test001"
        assert domain.account_id == "account_001"
        assert domain.security_code == "000001.SZ"
        assert domain.side == "BUY"
        assert domain.composite_score == 0.82
        assert domain.status == RecommendationStatus.NEW
        assert domain.user_action == UserDecisionAction.PENDING

    def test_from_domain(self, unified_recommendation_data):
        """测试从 Domain 实体创建"""
        from apps.decision_rhythm.domain.entities import UnifiedRecommendation

        # 将 status 从字符串转换为枚举
        data = unified_recommendation_data.copy()
        data["status"] = RecommendationStatus.NEW

        domain = UnifiedRecommendation(**data)
        model = UnifiedRecommendationModel.from_domain(domain)

        assert model.recommendation_id == "urec_test001"
        assert model.account_id == "account_001"
        assert model.security_code == "000001.SZ"

    def test_query_by_account_and_status(self, unified_recommendation_data):
        """测试按账户和状态查询"""
        UnifiedRecommendationModel.objects.create(**unified_recommendation_data)

        # 创建另一个不同状态的推荐
        data2 = unified_recommendation_data.copy()
        data2["recommendation_id"] = "urec_test002"
        data2["status"] = RecommendationStatus.APPROVED.value
        UnifiedRecommendationModel.objects.create(**data2)

        # 查询 NEW 状态的推荐
        new_recs = UnifiedRecommendationModel.objects.filter(
            account_id="account_001",
            status=RecommendationStatus.NEW.value,
        )
        assert new_recs.count() == 1

        # 查询 APPROVED 状态的推荐
        approved_recs = UnifiedRecommendationModel.objects.filter(
            account_id="account_001",
            status=RecommendationStatus.APPROVED.value,
        )
        assert approved_recs.count() == 1


@pytest.mark.django_db
class TestDecisionModelParamConfigModel:
    """测试决策模型参数配置"""

    def test_create_param_config(self):
        """测试创建参数配置"""
        config = DecisionModelParamConfigModel.objects.create(
            config_id="mpc_test001",
            param_key="alpha_model_weight",
            param_value="0.40",
            param_type="float",
            env="dev",
            version=1,
            is_active=True,
            description="Alpha 模型权重",
        )

        assert config.config_id == "mpc_test001"
        assert config.param_key == "alpha_model_weight"
        assert config.param_value == "0.40"
        assert config.param_type == "float"
        assert config.env == "dev"

    def test_get_typed_value_float(self):
        """测试获取类型化值（浮点数）"""
        config = DecisionModelParamConfigModel.objects.create(
            param_key="test_float",
            param_value="0.15",
            param_type="float",
        )
        assert config.to_domain().get_typed_value() == 0.15

    def test_get_typed_value_int(self):
        """测试获取类型化值（整数）"""
        config = DecisionModelParamConfigModel.objects.create(
            param_key="test_int",
            param_value="100",
            param_type="int",
        )
        assert config.to_domain().get_typed_value() == 100

    def test_get_typed_value_bool(self):
        """测试获取类型化值（布尔值）"""
        config = DecisionModelParamConfigModel.objects.create(
            param_key="test_bool",
            param_value="true",
            param_type="bool",
        )
        assert config.to_domain().get_typed_value() is True

        config.param_value = "false"
        config.save()
        assert config.to_domain().get_typed_value() is False

    def test_query_active_params_by_env(self):
        """测试按环境查询激活的参数"""
        # 使用唯一的参数键避免与现有数据冲突
        unique_key = "test_query_param_unique_001"

        # 清理可能存在的测试数据
        DecisionModelParamConfigModel.objects.filter(param_key=unique_key).delete()

        # 创建多个参数配置
        DecisionModelParamConfigModel.objects.create(
            param_key=unique_key,
            param_value="0.40",
            env="dev",
            is_active=True,
        )
        DecisionModelParamConfigModel.objects.create(
            param_key=unique_key,
            param_value="0.35",
            env="prod",
            is_active=True,
        )
        DecisionModelParamConfigModel.objects.create(
            param_key=unique_key,
            param_value="0.30",
            env="dev",
            is_active=False,
        )

        # 查询 dev 环境激活的参数
        dev_params = DecisionModelParamConfigModel.objects.filter(
            param_key=unique_key,
            env="dev",
            is_active=True,
        )
        assert dev_params.count() == 1
        assert dev_params.first().param_value == "0.40"

        # 清理测试数据
        DecisionModelParamConfigModel.objects.filter(param_key=unique_key).delete()


@pytest.mark.django_db
class TestDecisionModelParamAuditLogModel:
    """测试决策模型参数审计日志"""

    def test_create_audit_log(self):
        """测试创建审计日志"""
        log = DecisionModelParamAuditLogModel.objects.create(
            log_id="mpal_test001",
            param_key="alpha_model_weight",
            old_value="0.35",
            new_value="0.40",
            env="dev",
            changed_by="admin",
            change_reason="根据回测结果调整权重",
        )

        assert log.log_id == "mpal_test001"
        assert log.param_key == "alpha_model_weight"
        assert log.old_value == "0.35"
        assert log.new_value == "0.40"
        assert log.changed_by == "admin"

    def test_query_audit_logs_by_param(self):
        """测试按参数键查询审计日志"""
        # 使用唯一的参数键
        unique_key = "test_audit_param_unique_001"

        # 清理可能存在的测试数据
        DecisionModelParamAuditLogModel.objects.filter(param_key=unique_key).delete()

        DecisionModelParamAuditLogModel.objects.create(
            param_key=unique_key,
            old_value="0.30",
            new_value="0.35",
        )
        DecisionModelParamAuditLogModel.objects.create(
            param_key=unique_key,
            old_value="0.35",
            new_value="0.40",
        )
        DecisionModelParamAuditLogModel.objects.create(
            param_key=f"{unique_key}_other",
            old_value="0.10",
            new_value="0.15",
        )

        logs = DecisionModelParamAuditLogModel.objects.filter(
            param_key=unique_key
        ).order_by("-changed_at")
        assert logs.count() == 2

        # 清理测试数据
        DecisionModelParamAuditLogModel.objects.filter(
            param_key__startswith="test_audit_param_unique_001"
        ).delete()


@pytest.mark.django_db
class TestDecisionRequestModelExtensions:
    """测试 DecisionRequestModel 扩展字段"""

    def test_decision_request_with_unified_recommendation(self, unified_recommendation_data):
        """测试决策请求关联统一推荐"""
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)

        request = DecisionRequestModel.objects.create(
            request_id="req_test001",
            asset_code="000001.SZ",
            asset_class="EQUITY",
            direction="BUY",
            priority=DecisionPriority.HIGH.value,
            unified_recommendation=recommendation,
        )

        assert request.unified_recommendation is not None
        assert request.unified_recommendation.recommendation_id == "urec_test001"


@pytest.mark.django_db
class TestExecutionApprovalRequestModelExtensions:
    """测试 ExecutionApprovalRequestModel 扩展字段"""

    def test_execution_approval_with_unified_recommendation(self, unified_recommendation_data):
        """测试执行审批关联统一推荐"""
        recommendation = UnifiedRecommendationModel.objects.create(**unified_recommendation_data)

        # 创建投资建议（legacy）
        investment_rec = InvestmentRecommendationModel.objects.create(
            recommendation_id="rec_test001",
            security_code="000001.SZ",
            side="BUY",
            confidence=0.85,
            valuation_method="PE_BAND",
            fair_value=Decimal("15.50"),
            entry_price_low=Decimal("14.80"),
            entry_price_high=Decimal("15.20"),
            target_price_low=Decimal("18.00"),
            target_price_high=Decimal("20.00"),
            stop_loss_price=Decimal("13.50"),
        )

        approval = ExecutionApprovalRequestModel.objects.create(
            request_id="apr_test001",
            recommendation=investment_rec,
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            approval_status=ApprovalStatus.PENDING.value,
            suggested_quantity=1000,
            price_range_low=Decimal("14.80"),
            price_range_high=Decimal("15.20"),
            stop_loss_price=Decimal("13.50"),
            unified_recommendation=recommendation,
            execution_params_json={
                "limit_price": 15.0,
                "time_in_force": "DAY",
            },
        )

        assert approval.unified_recommendation is not None
        assert approval.unified_recommendation.recommendation_id == "urec_test001"
        assert approval.execution_params_json["limit_price"] == 15.0
