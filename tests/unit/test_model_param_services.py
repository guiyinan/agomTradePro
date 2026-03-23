"""
模型参数管理服务单元测试

测试 ModelWeights、GatePenalties、CompositeScoreCalculator、
RecommendationAggregator 等核心服务。
"""

from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from apps.decision_rhythm.application.use_cases import (
    GetModelParamsUseCase,
    UpdateModelParamRequest,
    UpdateModelParamUseCase,
)
from apps.decision_rhythm.domain.entities import (
    DecisionFeatureSnapshot,
    RecommendationStatus,
    UnifiedRecommendation,
)
from apps.decision_rhythm.domain.services import (
    DEFAULT_MODEL_PARAMS,
    CompositeScoreCalculator,
    ConflictPair,
    GatePenalties,
    ModelWeights,
    RecommendationAggregator,
)


class TestModelWeights:
    """测试模型权重配置"""

    def test_default_weights(self):
        """测试默认权重"""
        weights = ModelWeights()

        assert weights.alpha_model_weight == 0.40
        assert weights.sentiment_weight == 0.15
        assert weights.flow_weight == 0.15
        assert weights.technical_weight == 0.15
        assert weights.fundamental_weight == 0.15

    def test_validate_success(self):
        """测试验证成功（总和为 1）"""
        weights = ModelWeights()
        is_valid, error = weights.validate()

        assert is_valid is True
        assert error == ""

    def test_validate_failure_negative(self):
        """测试验证失败（负数）"""
        weights = ModelWeights(
            alpha_model_weight=-0.1,
        )
        is_valid, error = weights.validate()

        assert is_valid is False
        assert "负数" in error

    def test_validate_failure_sum_not_one(self):
        """测试验证失败（总和不为 1）"""
        weights = ModelWeights(
            alpha_model_weight=0.5,
            sentiment_weight=0.5,
            flow_weight=0.1,
        )
        is_valid, error = weights.validate()

        assert is_valid is False
        assert "1.0" in error


class TestGatePenalties:
    """测试 Gate 惩罚参数"""

    def test_default_penalties(self):
        """测试默认惩罚参数"""
        penalties = GatePenalties()

        assert penalties.cooldown_penalty == 0.10
        assert penalties.quota_penalty == 0.10
        assert penalties.volatility_penalty == 0.10


class TestCompositeScoreCalculator:
    """测试综合分计算器"""

    def test_calculate_base_score(self):
        """测试基础分数计算"""
        calculator = CompositeScoreCalculator()

        score, penalties = calculator.calculate(
            alpha_model_score=0.8,
            sentiment_score=0.7,
            flow_score=0.6,
            technical_score=0.7,
            fundamental_score=0.75,
        )

        # 基础分 = 0.4*0.8 + 0.15*0.7 + 0.15*0.6 + 0.15*0.7 + 0.15*0.75
        #       = 0.32 + 0.105 + 0.09 + 0.105 + 0.1125 = 0.7325
        assert abs(score - 0.7325) < 0.001
        assert len(penalties) == 0

    def test_calculate_with_penalties(self):
        """测试带惩罚的分数计算"""
        calculator = CompositeScoreCalculator()

        score, penalties = calculator.calculate(
            alpha_model_score=0.8,
            sentiment_score=0.7,
            flow_score=0.6,
            technical_score=0.7,
            fundamental_score=0.75,
            cooldown_violation=True,
            quota_tight=True,
        )

        # 基础分 0.7325 - 0.1(冷却) - 0.1(配额) = 0.5325
        assert abs(score - 0.5325) < 0.001
        assert "COOLDOWN_VIOLATION" in penalties
        assert "QUOTA_TIGHT" in penalties
        assert "VOLATILITY_HIGH" not in penalties

    def test_calculate_score_not_negative(self):
        """测试分数不会为负"""
        calculator = CompositeScoreCalculator()

        score, penalties = calculator.calculate(
            alpha_model_score=0.1,
            sentiment_score=0.1,
            flow_score=0.1,
            technical_score=0.1,
            fundamental_score=0.1,
            cooldown_violation=True,
            quota_tight=True,
            volatility_high=True,
        )

        # 基础分很低，惩罚很高，但分数不能为负
        assert score >= 0

    def test_calculate_from_snapshot(self):
        """测试从特征快照计算"""
        calculator = CompositeScoreCalculator()

        snapshot = DecisionFeatureSnapshot(
            snapshot_id="fsn_001",
            security_code="000001.SZ",
            snapshot_time=datetime.now(UTC),
            alpha_model_score=0.85,
            sentiment_score=0.72,
            flow_score=0.68,
            technical_score=0.78,
            fundamental_score=0.81,
        )

        score, penalties = calculator.calculate_from_snapshot(
            snapshot=snapshot,
            volatility_high=True,
        )

        # 验证分数计算正确
        assert score > 0
        assert "VOLATILITY_HIGH" in penalties

    def test_custom_weights(self):
        """测试自定义权重"""
        weights = ModelWeights(
            alpha_model_weight=0.5,
            sentiment_weight=0.2,
            flow_weight=0.1,
            technical_weight=0.1,
            fundamental_weight=0.1,
        )
        calculator = CompositeScoreCalculator(weights=weights)

        score, _ = calculator.calculate(
            alpha_model_score=1.0,
            sentiment_score=0.0,
            flow_score=0.0,
            technical_score=0.0,
            fundamental_score=0.0,
        )

        # 只用 alpha 权重 0.5
        assert abs(score - 0.5) < 0.001


class TestRecommendationAggregator:
    """测试推荐聚合器"""

    def _create_recommendation(
        self,
        recommendation_id: str,
        account_id: str,
        security_code: str,
        side: str,
        confidence: float = 0.8,
    ) -> UnifiedRecommendation:
        """创建测试推荐"""
        return UnifiedRecommendation(
            recommendation_id=recommendation_id,
            account_id=account_id,
            security_code=security_code,
            side=side,
            confidence=confidence,
            composite_score=confidence,
        )

    def test_aggregate_single_recommendation(self):
        """测试单个推荐聚合"""
        aggregator = RecommendationAggregator()

        rec = self._create_recommendation(
            "urec_001", "account_001", "000001.SZ", "BUY"
        )
        deduplicated, conflicts, conflict_pairs = aggregator.aggregate([rec])

        assert len(deduplicated) == 1
        assert len(conflicts) == 0
        assert len(conflict_pairs) == 0

    def test_aggregate_duplicate_recommendations(self):
        """测试重复推荐聚合（同账户同证券同方向）"""
        aggregator = RecommendationAggregator()

        rec1 = self._create_recommendation(
            "urec_001", "account_001", "000001.SZ", "BUY", confidence=0.8
        )
        rec2 = self._create_recommendation(
            "urec_002", "account_001", "000001.SZ", "BUY", confidence=0.9
        )

        deduplicated, conflicts, conflict_pairs = aggregator.aggregate([rec1, rec2])

        # 应该合并为一个，保留高置信度的
        assert len(deduplicated) == 1
        assert deduplicated[0].confidence == 0.9
        assert len(conflicts) == 0

    def test_aggregate_buy_sell_conflict(self):
        """测试 BUY/SELL 冲突检测"""
        aggregator = RecommendationAggregator()

        buy_rec = self._create_recommendation(
            "urec_buy", "account_001", "000001.SZ", "BUY"
        )
        sell_rec = self._create_recommendation(
            "urec_sell", "account_001", "000001.SZ", "SELL"
        )

        deduplicated, conflicts, conflict_pairs = aggregator.aggregate([buy_rec, sell_rec])

        # 两个都应该进入冲突列表
        assert len(deduplicated) == 0
        assert len(conflicts) == 2
        assert len(conflict_pairs) == 1
        assert conflict_pairs[0].buy_recommendation.recommendation_id == "urec_buy"
        assert conflict_pairs[0].sell_recommendation.recommendation_id == "urec_sell"

    def test_aggregate_different_accounts(self):
        """测试不同账户的推荐（不冲突）"""
        aggregator = RecommendationAggregator()

        rec1 = self._create_recommendation(
            "urec_001", "account_001", "000001.SZ", "BUY"
        )
        rec2 = self._create_recommendation(
            "urec_002", "account_002", "000001.SZ", "BUY"
        )

        deduplicated, conflicts, conflict_pairs = aggregator.aggregate([rec1, rec2])

        # 不同账户，不冲突
        assert len(deduplicated) == 2
        assert len(conflicts) == 0

    def test_aggregate_merges_reason_codes(self):
        """测试合并原因代码"""
        aggregator = RecommendationAggregator()

        rec1 = UnifiedRecommendation(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            confidence=0.8,
            reason_codes=["ALPHA_HIGH", "REGIME_FAVORABLE"],
        )
        rec2 = UnifiedRecommendation(
            recommendation_id="urec_002",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            confidence=0.7,
            reason_codes=["SENTIMENT_POSITIVE", "ALPHA_HIGH"],
        )

        deduplicated, _, _ = aggregator.aggregate([rec1, rec2])

        # 合并后的原因代码应该去重
        merged_reasons = deduplicated[0].reason_codes
        assert "ALPHA_HIGH" in merged_reasons
        assert "REGIME_FAVORABLE" in merged_reasons
        assert "SENTIMENT_POSITIVE" in merged_reasons
        # 去重后只有 3 个
        assert len(set(merged_reasons)) == 3


class TestConflictPair:
    """测试冲突对"""

    def test_create_conflict_pair(self):
        """测试创建冲突对"""
        buy_rec = UnifiedRecommendation(
            recommendation_id="urec_buy",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
        )
        sell_rec = UnifiedRecommendation(
            recommendation_id="urec_sell",
            account_id="account_001",
            security_code="000001.SZ",
            side="SELL",
        )

        pair = ConflictPair(
            buy_recommendation=buy_rec,
            sell_recommendation=sell_rec,
        )

        assert pair.buy_recommendation.side == "BUY"
        assert pair.sell_recommendation.side == "SELL"


class TestGetModelParamsUseCase:
    """测试获取模型参数用例"""

    def test_execute_returns_default_params(self):
        """测试返回默认参数（无数据库配置时）"""
        # Mock 仓储返回空列表
        mock_repo = MagicMock()
        mock_repo.get_all_params.return_value = []

        use_case = GetModelParamsUseCase(mock_repo, default_env="dev")
        params = use_case.execute()

        # 应该返回默认值
        assert params["alpha_model_weight"] == 0.40
        assert params["sentiment_weight"] == 0.15

    def test_execute_merges_db_params(self):
        """测试合并数据库配置"""
        from apps.decision_rhythm.domain.entities import ModelParamConfig

        # Mock 仓储返回数据库配置
        mock_repo = MagicMock()
        mock_config = ModelParamConfig(
            config_id="mpc_001",
            param_key="alpha_model_weight",
            param_value="0.50",  # 覆盖默认值
            param_type="float",
            env="dev",
            is_active=True,
        )
        mock_repo.get_all_params.return_value = [mock_config]

        use_case = GetModelParamsUseCase(mock_repo, default_env="dev")
        params = use_case.execute()

        # 数据库配置应该覆盖默认值
        assert params["alpha_model_weight"] == 0.50
        # 其他参数使用默认值
        assert params["sentiment_weight"] == 0.15

    def test_get_param_returns_default(self):
        """测试获取单个参数的默认值"""
        mock_repo = MagicMock()
        mock_repo.get_param.return_value = None

        use_case = GetModelParamsUseCase(mock_repo)
        value = use_case.get_param("alpha_model_weight")

        assert value == 0.40

    def test_get_model_weights(self):
        """测试获取模型权重配置"""
        mock_repo = MagicMock()
        mock_repo.get_all_params.return_value = []

        use_case = GetModelParamsUseCase(mock_repo)
        weights = use_case.get_model_weights()

        assert isinstance(weights, ModelWeights)
        assert weights.alpha_model_weight == 0.40

    def test_get_gate_penalties(self):
        """测试获取 Gate 惩罚参数"""
        mock_repo = MagicMock()
        mock_repo.get_all_params.return_value = []

        use_case = GetModelParamsUseCase(mock_repo)
        penalties = use_case.get_gate_penalties()

        assert isinstance(penalties, GatePenalties)
        assert penalties.cooldown_penalty == 0.10


class TestUpdateModelParamUseCase:
    """测试更新模型参数用例"""

    def test_execute_creates_new_param(self):
        """测试创建新参数"""
        from apps.decision_rhythm.domain.entities import ModelParamConfig

        mock_repo = MagicMock()
        mock_repo.get_param.return_value = None
        mock_repo.save_param.return_value = ModelParamConfig(
            config_id="mpc_new",
            param_key="test_param",
            param_value="0.5",
            env="dev",
        )

        use_case = UpdateModelParamUseCase(mock_repo)
        response = use_case.execute(UpdateModelParamRequest(
            param_key="test_param",
            param_value="0.5",
            env="dev",
            updated_by="test_user",
            updated_reason="test",
        ))

        assert response.success is True
        mock_repo.create_audit_log.assert_called_once()

    def test_execute_updates_existing_param(self):
        """测试更新现有参数"""
        from apps.decision_rhythm.domain.entities import ModelParamConfig

        # 模拟现有配置
        existing_config = ModelParamConfig(
            config_id="mpc_001",
            param_key="alpha_model_weight",
            param_value="0.40",
            env="dev",
            version=1,
        )

        mock_repo = MagicMock()
        mock_repo.get_param.return_value = existing_config
        mock_repo.save_param.return_value = ModelParamConfig(
            config_id="mpc_001",
            param_key="alpha_model_weight",
            param_value="0.45",
            env="dev",
            version=2,
        )

        use_case = UpdateModelParamUseCase(mock_repo)
        response = use_case.execute(UpdateModelParamRequest(
            param_key="alpha_model_weight",
            param_value="0.45",
            env="dev",
            updated_by="test_user",
            updated_reason="优化权重",
        ))

        assert response.success is True
        mock_repo.create_audit_log.assert_called_once()

        # 验证审计日志包含旧值和新值
        audit_call = mock_repo.create_audit_log.call_args
        audit_log = audit_call[0][0]
        assert audit_log.old_value == "0.40"
        assert audit_log.new_value == "0.45"
