"""
Unit Tests for Alpha Trigger Domain Entities

测试 AlphaTrigger 和 AlphaCandidate 实体的行为。
"""

import pytest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.alpha_trigger.domain.entities import (
    AlphaTrigger,
    AlphaCandidate,
    TriggerType,
    TriggerStatus,
    SignalStrength,
    InvalidationCondition,
    InvalidationType,
    CandidateStatus,
)


class TestInvalidationCondition:
    """InvalidationCondition 实体测试"""

    def test_indicator_invalidaton_condition(self):
        """测试指标证伪条件"""
        condition = InvalidationCondition(
            condition_type=InvalidationType.INDICATOR,
            indicator_code="CN_PMI_MANUFACTURING",
            threshold=49.5,
            direction="below",
        )

        assert condition.condition_type == InvalidationType.INDICATOR
        assert condition.indicator_code == "CN_PMI_MANUFACTURING"
        assert condition.threshold == 49.5
        assert condition.direction == "below"

    def test_time_decay_condition(self):
        """测试时间衰减证伪条件"""
        condition = InvalidationCondition(
            condition_type=InvalidationType.TIME_DECAY,
            time_limit_hours=72,
        )

        assert condition.condition_type == InvalidationType.TIME_DECAY
        assert condition.time_limit_hours == 72

    def test_regime_mismatch_condition(self):
        """测试 Regime 不匹配证伪条件"""
        condition = InvalidationCondition(
            condition_type=InvalidationType.REGIME_MISMATCH,
            custom_condition={
                "expected_regime": "Recovery",
                "forbidden_regimes": ["Slowdown", "Downturn"],
            },
        )

        assert condition.condition_type == InvalidationType.REGIME_MISMATCH
        assert condition.custom_condition["expected_regime"] == "Recovery"

    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        original = InvalidationCondition(
            condition_type=InvalidationType.INDICATOR,
            indicator_code="CN_PMI_MANUFACTURING",
            threshold=49.5,
            direction="below",
        )

        data = original.to_dict()
        restored = InvalidationCondition.from_dict(data)

        assert restored.condition_type == original.condition_type
        assert restored.indicator_code == original.indicator_code
        assert restored.threshold == original.threshold
        assert restored.direction == original.direction


class TestAlphaTrigger:
    """AlphaTrigger 实体测试"""

    @pytest.fixture
    def base_trigger(self):
        """基础触发器 fixture"""
        return AlphaTrigger(
            trigger_id="test_trigger_001",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={"momentum_pct": 0.05},
            invalidation_conditions=[
                InvalidationCondition(
                    condition_type=InvalidationType.INDICATOR,
                    indicator_code="CN_PMI_MANUFACTURING",
                    threshold=49.5,
                    direction="below",
                ),
            ],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.ACTIVE,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            expires_at=datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=90),
            thesis="PMI 连续回升，经济复苏信号明确",
        )

    def test_trigger_creation(self, base_trigger):
        """测试触发器创建"""
        assert base_trigger.trigger_id == "test_trigger_001"
        assert base_trigger.trigger_type == TriggerType.MOMENTUM_SIGNAL
        assert base_trigger.asset_code == "000001.SH"
        assert base_trigger.direction == "LONG"
        assert base_trigger.strength == SignalStrength.STRONG
        assert base_trigger.confidence == 0.75

    def test_trigger_status_transitions(self, base_trigger):
        """测试触发器状态转换"""
        # Active -> Triggered
        base_trigger.status = TriggerStatus.TRIGGERED
        base_trigger.triggered_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        assert base_trigger.is_triggered is True
        assert base_trigger.is_active is False

        # Triggered -> Invalidated
        base_trigger.status = TriggerStatus.INVALIDATED
        base_trigger.invalidated_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        assert base_trigger.is_invalidated is True

    def test_trigger_expiration(self, base_trigger):
        """测试触发器过期"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        base_trigger.expires_at = now - timedelta(days=1)

        assert base_trigger.is_expired is True

    def test_trigger_strength_levels(self):
        """测试信号强度级别"""
        strengths = [
            SignalStrength.VERY_WEAK,
            SignalStrength.WEAK,
            SignalStrength.MODERATE,
            SignalStrength.STRONG,
            SignalStrength.VERY_STRONG,
        ]

        for strength in strengths:
            trigger = AlphaTrigger(
                trigger_id=f"test_{strength.value}",
                trigger_type=TriggerType.MOMENTUM_SIGNAL,
                asset_code="000001.SH",
                asset_class="a_share金融",
                direction="LONG",
                trigger_condition={},
                invalidation_conditions=[],
                strength=strength,
                confidence=0.5,
                status=TriggerStatus.ACTIVE,
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            assert trigger.strength == strength


class TestAlphaCandidate:
    """AlphaCandidate 实体测试"""

    @pytest.fixture
    def base_candidate(self):
        """基础候选 fixture"""
        return AlphaCandidate(
            candidate_id="test_candidate_001",
            trigger_id="test_trigger_001",
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=CandidateStatus.WATCH,
            thesis="PMI 连续回升，经济复苏信号明确",
            entry_zone={"price": 15.0, "range": 0.02},
            exit_zone={"price": 18.0, "range": 0.01},
            time_horizon=90,
            expected_return=0.20,
            risk_level="MEDIUM",
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    def test_candidate_creation(self, base_candidate):
        """测试候选创建"""
        assert base_candidate.candidate_id == "test_candidate_001"
        assert base_candidate.trigger_id == "test_trigger_001"
        assert base_candidate.asset_code == "000001.SH"
        assert base_candidate.status == CandidateStatus.WATCH
        assert base_candidate.time_horizon == 90

    def test_candidate_status_promotion(self, base_candidate):
        """测试候选状态提升"""
        # WATCH -> CANDIDATE
        base_candidate.status = CandidateStatus.CANDIDATE
        base_candidate.status_changed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        assert base_candidate.status == CandidateStatus.CANDIDATE

        # CANDIDATE -> ACTIONABLE
        base_candidate.status = CandidateStatus.ACTIONABLE
        assert base_candidate.is_actionable is True

        # ACTIONABLE -> EXECUTED
        base_candidate.status = CandidateStatus.EXECUTED
        base_candidate.promoted_to_signal_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        assert base_candidate.status == CandidateStatus.EXECUTED

    def test_candidate_entry_exit_zones(self, base_candidate):
        """测试入场出场区域"""
        assert base_candidate.entry_zone == {"price": 15.0, "range": 0.02}
        assert base_candidate.exit_zone == {"price": 18.0, "range": 0.01}
        assert base_candidate.expected_return == 0.20

    def test_candidate_time_horizon(self, base_candidate):
        """测试时间窗口"""
        assert base_candidate.time_horizon == 90  # 90 天

        # 短期
        base_candidate.time_horizon = 30
        assert base_candidate.time_horizon == 30

        # 长期
        base_candidate.time_horizon = 180
        assert base_candidate.time_horizon == 180
