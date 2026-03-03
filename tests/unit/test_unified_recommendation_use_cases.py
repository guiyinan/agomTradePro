"""
统一推荐聚合服务单元测试

测试 GenerateUnifiedRecommendationsUseCase、GetUnifiedRecommendationsUseCase、
GetConflictsUseCase 等用例。
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from apps.decision_rhythm.application.use_cases import (
    GenerateUnifiedRecommendationsUseCase,
    GenerateRecommendationsRequest,
    GenerateRecommendationsResponse,
    GetUnifiedRecommendationsUseCase,
    GetRecommendationsRequest,
    GetConflictsUseCase,
    GetConflictsRequest,
    GetModelParamsUseCase,
)
from apps.decision_rhythm.domain.entities import (
    UnifiedRecommendation,
    DecisionFeatureSnapshot,
    RecommendationStatus,
)


# ============================================================================
# Mock 提供者
# ============================================================================


class MockFeatureDataProvider:
    """Mock 特征数据提供者"""

    def __init__(self):
        self._regime = {"regime": "GROWTH_INFLATION", "confidence": 0.85}
        self._policy_level = "LEVEL_2"
        self._beta_gate_results: Dict[str, bool] = {}
        self._scores: Dict[str, Dict[str, float]] = {}

    def get_regime(self) -> Optional[Dict[str, Any]]:
        return self._regime

    def get_policy_level(self) -> Optional[str]:
        return self._policy_level

    def check_beta_gate(self, security_code: str) -> bool:
        return self._beta_gate_results.get(security_code, True)

    def get_sentiment_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("sentiment", 0.7)

    def get_flow_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("flow", 0.65)

    def get_technical_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("technical", 0.75)

    def get_fundamental_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("fundamental", 0.8)

    def get_alpha_model_score(self, security_code: str) -> float:
        return self._scores.get(security_code, {}).get("alpha", 0.85)

    def set_beta_gate(self, security_code: str, passed: bool):
        self._beta_gate_results[security_code] = passed

    def set_scores(self, security_code: str, scores: Dict[str, float]):
        if security_code not in self._scores:
            self._scores[security_code] = {}
        self._scores[security_code].update(scores)


class MockValuationProvider:
    """Mock 估值数据提供者"""

    def __init__(self):
        self._valuations: Dict[str, Dict[str, Any]] = {}

    def get_valuation(self, security_code: str) -> Optional[Dict[str, Any]]:
        return self._valuations.get(security_code)

    def set_valuation(self, security_code: str, valuation: Dict[str, Any]):
        self._valuations[security_code] = valuation


class MockSignalProvider:
    """Mock 信号数据提供者"""

    def __init__(self):
        self._signals: List[Dict[str, Any]] = []

    def get_active_signals(self, security_code: Optional[str] = None) -> List[Dict[str, Any]]:
        if security_code:
            return [s for s in self._signals if s.get("security_code") == security_code]
        return self._signals

    def add_signal(self, signal_id: str, security_code: str):
        self._signals.append({"signal_id": signal_id, "security_code": security_code})


class MockCandidateProvider:
    """Mock 候选数据提供者"""

    def __init__(self):
        self._candidates: List[Dict[str, Any]] = []

    def get_active_candidates(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if account_id:
            return [c for c in self._candidates if c.get("account_id") == account_id]
        return self._candidates

    def add_candidate(self, candidate_id: str, account_id: str, security_code: str):
        self._candidates.append({
            "candidate_id": candidate_id,
            "account_id": account_id,
            "security_code": security_code,
        })


class MockRecommendationRepository:
    """Mock 推荐仓储"""

    def __init__(self):
        self._recommendations: Dict[str, UnifiedRecommendation] = {}
        self._snapshots: Dict[str, DecisionFeatureSnapshot] = {}
        self._conflicts: List[str] = []

    def save(self, recommendation: UnifiedRecommendation) -> UnifiedRecommendation:
        self._recommendations[recommendation.recommendation_id] = recommendation
        return recommendation

    def save_feature_snapshot(self, snapshot: DecisionFeatureSnapshot) -> DecisionFeatureSnapshot:
        self._snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def get_by_account(
        self,
        account_id: str,
        status: Optional[str] = None,
    ) -> List[UnifiedRecommendation]:
        result = [
            r for r in self._recommendations.values()
            if r.account_id == account_id and r.recommendation_id not in self._conflicts
        ]
        if status:
            result = [r for r in result if r.status.value == status]
        return result

    def get_conflicts(self, account_id: str) -> List[UnifiedRecommendation]:
        return [
            r for r in self._recommendations.values()
            if r.account_id == account_id and r.recommendation_id in self._conflicts
        ]

    def mark_as_conflict(self, recommendation_id: str) -> None:
        self._conflicts.append(recommendation_id)


# ============================================================================
# 测试类
# ============================================================================


class TestGenerateUnifiedRecommendationsUseCase:
    """测试生成统一推荐用例"""

    @pytest.fixture
    def setup(self):
        """设置测试环境"""
        feature_provider = MockFeatureDataProvider()
        valuation_provider = MockValuationProvider()
        signal_provider = MockSignalProvider()
        candidate_provider = MockCandidateProvider()
        recommendation_repo = MockRecommendationRepository()

        # Mock 参数用例
        param_use_case = MagicMock(spec=GetModelParamsUseCase)
        param_use_case.get_model_weights.return_value = MagicMock(
            alpha_model_weight=0.40,
            sentiment_weight=0.15,
            flow_weight=0.15,
            technical_weight=0.15,
            fundamental_weight=0.15,
        )
        param_use_case.get_gate_penalties.return_value = MagicMock(
            cooldown_penalty=0.10,
            quota_penalty=0.10,
            volatility_penalty=0.10,
        )

        use_case = GenerateUnifiedRecommendationsUseCase(
            feature_provider=feature_provider,
            valuation_provider=valuation_provider,
            signal_provider=signal_provider,
            candidate_provider=candidate_provider,
            recommendation_repo=recommendation_repo,
            param_use_case=param_use_case,
        )

        return {
            "use_case": use_case,
            "feature_provider": feature_provider,
            "valuation_provider": valuation_provider,
            "signal_provider": signal_provider,
            "candidate_provider": candidate_provider,
            "recommendation_repo": recommendation_repo,
        }

    def test_generate_single_recommendation(self, setup):
        """测试生成单个推荐"""
        # 设置数据
        setup["feature_provider"].set_scores("000001.SZ", {
            "sentiment": 0.75,
            "flow": 0.70,
            "technical": 0.80,
            "fundamental": 0.82,
            "alpha": 0.88,
        })
        setup["valuation_provider"].set_valuation("000001.SZ", {
            "fair_value": 15.50,
            "entry_price_low": 14.80,
            "entry_price_high": 15.20,
            "target_price_low": 18.00,
            "target_price_high": 20.00,
            "stop_loss_price": 13.50,
        })

        # 执行
        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        # 验证
        assert response.success is True
        assert len(response.recommendations) == 1
        assert len(response.conflicts) == 0

        rec = response.recommendations[0]
        assert rec.security_code == "000001.SZ"
        assert rec.account_id == "account_001"
        assert rec.side in ["BUY", "SELL", "HOLD"]
        assert rec.composite_score > 0
        assert rec.beta_gate_passed is True

    def test_generate_filters_beta_gate_failed(self, setup):
        """测试 Beta Gate 不通过时过滤"""
        # 设置数据
        setup["feature_provider"].set_beta_gate("000001.SZ", False)
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.9})

        # 执行
        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        # 验证：应该被过滤
        assert response.success is True
        assert len(response.recommendations) == 0

    def test_generate_with_valuation_data(self, setup):
        """测试包含估值数据"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})
        setup["valuation_provider"].set_valuation("000001.SZ", {
            "fair_value": 20.00,
            "entry_price_low": 19.00,
            "entry_price_high": 19.50,
            "target_price_low": 25.00,
            "target_price_high": 28.00,
            "stop_loss_price": 17.00,
        })

        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        assert response.success is True
        rec = response.recommendations[0]
        assert rec.fair_value == Decimal("20.00")
        assert rec.entry_price_low == Decimal("19.00")
        assert rec.stop_loss_price == Decimal("17.00")

    def test_generate_with_sources(self, setup):
        """测试包含来源信号和候选"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})
        setup["signal_provider"].add_signal("sig_001", "000001.SZ")
        setup["signal_provider"].add_signal("sig_002", "000001.SZ")
        setup["candidate_provider"].add_candidate("cand_001", "account_001", "000001.SZ")

        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        assert response.success is True
        rec = response.recommendations[0]
        assert "sig_001" in rec.source_signal_ids
        assert "sig_002" in rec.source_signal_ids
        assert "cand_001" in rec.source_candidate_ids

    def test_generate_determines_buy_side(self, setup):
        """测试确定 BUY 方向"""
        # 高分数应该生成 BUY
        setup["feature_provider"].set_scores("000001.SZ", {
            "sentiment": 0.80,
            "flow": 0.75,
            "technical": 0.82,
            "fundamental": 0.85,
            "alpha": 0.90,  # 高 Alpha
        })

        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        assert response.success is True
        rec = response.recommendations[0]
        # 高分数应该是 BUY
        assert rec.side == "BUY"

    def test_generate_saves_feature_snapshot(self, setup):
        """测试保存特征快照"""
        setup["feature_provider"].set_scores("000001.SZ", {"alpha": 0.85})

        response = setup["use_case"].execute(GenerateRecommendationsRequest(
            account_id="account_001",
            security_codes=["000001.SZ"],
        ))

        assert response.success is True
        # 验证快照已保存
        assert len(setup["recommendation_repo"]._snapshots) == 1


class TestGetUnifiedRecommendationsUseCase:
    """测试获取统一推荐用例"""

    def test_get_recommendations(self):
        """测试获取推荐列表"""
        repo = MockRecommendationRepository()
        repo.save(UnifiedRecommendation(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            status=RecommendationStatus.NEW,
        ))
        repo.save(UnifiedRecommendation(
            recommendation_id="urec_002",
            account_id="account_001",
            security_code="000002.SZ",
            side="BUY",
            status=RecommendationStatus.APPROVED,
        ))

        use_case = GetUnifiedRecommendationsUseCase(repo)
        response = use_case.execute(GetRecommendationsRequest(
            account_id="account_001",
        ))

        assert response.success is True
        assert len(response.recommendations) == 2
        assert response.total_count == 2

    def test_get_recommendations_by_status(self):
        """测试按状态获取推荐"""
        repo = MockRecommendationRepository()
        repo.save(UnifiedRecommendation(
            recommendation_id="urec_001",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            status=RecommendationStatus.NEW,
        ))
        repo.save(UnifiedRecommendation(
            recommendation_id="urec_002",
            account_id="account_001",
            security_code="000002.SZ",
            side="BUY",
            status=RecommendationStatus.APPROVED,
        ))

        use_case = GetUnifiedRecommendationsUseCase(repo)
        response = use_case.execute(GetRecommendationsRequest(
            account_id="account_001",
            status="APPROVED",
        ))

        assert response.success is True
        assert len(response.recommendations) == 1
        assert response.recommendations[0].status == RecommendationStatus.APPROVED


class TestGetConflictsUseCase:
    """测试获取冲突用例"""

    def test_get_conflicts(self):
        """测试获取冲突列表"""
        repo = MockRecommendationRepository()

        # 保存冲突推荐
        conflict_rec = UnifiedRecommendation(
            recommendation_id="urec_conflict",
            account_id="account_001",
            security_code="000001.SZ",
            side="BUY",
            status=RecommendationStatus.CONFLICT,
        )
        repo.save(conflict_rec)
        repo.mark_as_conflict("urec_conflict")

        # 保存非冲突推荐
        repo.save(UnifiedRecommendation(
            recommendation_id="urec_normal",
            account_id="account_001",
            security_code="000002.SZ",
            side="BUY",
            status=RecommendationStatus.NEW,
        ))

        use_case = GetConflictsUseCase(repo)
        response = use_case.execute(GetConflictsRequest(
            account_id="account_001",
        ))

        assert response.success is True
        assert len(response.conflicts) == 1
        assert response.conflicts[0].recommendation_id == "urec_conflict"
