"""
Unit Tests for Alpha Trigger Domain Services

测试 TriggerEvaluator, TriggerInvalidator 和 CandidateGenerator 的行为。
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
    CandidateStatus,
    InvalidationCondition,
    InvalidationType,
    InvalidationCheckResult,
)
from apps.alpha_trigger.domain.services import (
    TriggerEvaluator,
    TriggerInvalidator,
    CandidateGenerator,
    TriggerConfig,
    calculate_strength,
)


class TestTriggerConfig:
    """TriggerConfig 测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = TriggerConfig()

        assert config is not None
        assert isinstance(config.strength_thresholds, dict)
        assert SignalStrength.VERY_STRONG in config.strength_thresholds

    def test_get_strength(self):
        """测试根据置信度获取强度"""
        config = TriggerConfig()

        # 高置信度 -> 非常强
        strength = config.get_strength(0.85)
        assert strength == SignalStrength.VERY_STRONG

        # 中等置信度 -> 中等
        strength = config.get_strength(0.5)
        assert strength == SignalStrength.MODERATE

        # 低置信度 -> 弱
        strength = config.get_strength(0.2)
        assert strength == SignalStrength.WEAK


class TestCalculateStrength:
    """calculate_strength 函数测试"""

    def test_very_strong_strength(self):
        """测试非常强信号"""
        strength = calculate_strength(0.85)
        assert strength == SignalStrength.VERY_STRONG

    def test_strong_strength(self):
        """测试强信号"""
        strength = calculate_strength(0.70)
        assert strength == SignalStrength.STRONG

    def test_moderate_strength(self):
        """测试中等信号"""
        strength = calculate_strength(0.50)
        assert strength == SignalStrength.MODERATE

    def test_weak_strength(self):
        """测试弱信号"""
        strength = calculate_strength(0.30)
        assert strength == SignalStrength.WEAK

    def test_very_weak_strength(self):
        """测试非常弱信号"""
        strength = calculate_strength(0.15)
        assert strength == SignalStrength.VERY_WEAK


class TestTriggerEvaluator:
    """TriggerEvaluator 测试"""

    @pytest.fixture
    def config(self):
        """配置 fixture"""
        return TriggerConfig()

    @pytest.fixture
    def evaluator(self, config):
        """评估器 fixture"""
        return TriggerEvaluator(config)

    @pytest.fixture
    def trigger(self):
        """触发器 fixture"""
        return AlphaTrigger(
            trigger_id="test_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={"momentum_pct": 0.05},
            invalidation_conditions=[],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.ACTIVE,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    def test_should_trigger_met_condition(self, evaluator, trigger):
        """测试满足触发条件"""
        current_data = {
            "momentum_pct": 0.06,  # 超过 0.05 阈值
        }

        should_trigger, reason = evaluator.should_trigger(trigger, current_data)

        assert should_trigger is True
        assert "momentum" in reason.lower()

    def test_should_trigger_not_met_condition(self, evaluator, trigger):
        """测试不满足触发条件"""
        current_data = {
            "momentum_pct": 0.03,  # 低于 0.05 阈值
        }

        should_trigger, reason = evaluator.should_trigger(trigger, current_data)

        assert should_trigger is False
        assert "not met" in reason.lower() or "below" in reason.lower()

    def test_should_trigger_inactive(self, evaluator, trigger):
        """测试非活跃触发器"""
        trigger.status = TriggerStatus.INVALIDATED

        should_trigger, reason = evaluator.should_trigger(trigger, {})

        assert should_trigger is False
        assert "inactive" in reason.lower() or "invalid" in reason.lower()


class TestTriggerInvalidator:
    """TriggerInvalidator 测试"""

    @pytest.fixture
    def invalidator(self):
        """证伪器 fixture"""
        return TriggerInvalidator()

    @pytest.fixture
    def trigger_with_indicator_condition(self):
        """带指标条件的触发器 fixture"""
        return AlphaTrigger(
            trigger_id="test_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={},
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
            status=TriggerStatus.TRIGGERED,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            triggered_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

    def test_check_invalidations_not_met(self, invalidator, trigger_with_indicator_condition):
        """测试证伪条件不满足"""
        current_data = {
            "CN_PMI_MANUFACTURING": 50.5,  # 高于 49.5
        }

        result = invalidator.check_invalidations(trigger_with_indicator_condition, current_data)

        assert result.is_invalidated is False
        assert result.conditions_met == []

    def test_check_invalidations_met(self, invalidator, trigger_with_indicator_condition):
        """测试证伪条件满足"""
        current_data = {
            "CN_PMI_MANUFACTURING": 49.0,  # 低于 49.5
        }

        result = invalidator.check_invalidations(trigger_with_indicator_condition, current_data)

        assert result.is_invalidated is True
        assert len(result.conditions_met) > 0
        assert "CN_PMI_MANUFACTURING" in result.reason

    def test_check_invalidations_time_decay(self, invalidator):
        """测试时间衰减证伪"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        trigger = AlphaTrigger(
            trigger_id="test_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={},
            invalidation_conditions=[
                InvalidationCondition(
                    condition_type=InvalidationType.TIME_DECAY,
                    time_limit_hours=72,
                ),
            ],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.TRIGGERED,
            created_at=now - timedelta(days=10),
            triggered_at=now - timedelta(hours=80),  # 80 小时前触发
        )

        current_data = {
            "triggered_at": now - timedelta(hours=80),
        }

        result = invalidator.check_invalidations(trigger, current_data)

        assert result.is_invalidated is True
        assert "time" in result.reason.lower()


class TestCandidateGenerator:
    """CandidateGenerator 测试"""

    @pytest.fixture
    def generator(self):
        """生成器 fixture"""
        return CandidateGenerator()

    @pytest.fixture
    def triggered_trigger(self):
        """已触发触发器 fixture"""
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        return AlphaTrigger(
            trigger_id="test_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={},
            invalidation_conditions=[],
            strength=SignalStrength.STRONG,
            confidence=0.75,
            status=TriggerStatus.TRIGGERED,
            created_at=now - timedelta(days=5),
            triggered_at=now - timedelta(hours=2),
            thesis="PMI 连续回升，经济复苏信号明确",
        )

    def test_from_trigger(self, generator, triggered_trigger):
        """测试从触发器生成候选"""
        candidate = generator.from_trigger(triggered_trigger, time_window_days=90)

        assert candidate.trigger_id == triggered_trigger.trigger_id
        assert candidate.asset_code == triggered_trigger.asset_code
        assert candidate.asset_class == triggered_trigger.asset_class
        assert candidate.direction == triggered_trigger.direction
        assert candidate.strength == triggered_trigger.strength
        assert candidate.confidence == triggered_trigger.confidence
        assert candidate.thesis == triggered_trigger.thesis
        assert candidate.time_horizon == 90

    def test_candidate_status_based_on_strength(self, generator):
        """测试基于强度的候选状态"""
        # 非常强 -> ACTIONABLE
        strong_trigger = AlphaTrigger(
            trigger_id="strong_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={},
            invalidation_conditions=[],
            strength=SignalStrength.VERY_STRONG,
            confidence=0.85,
            status=TriggerStatus.TRIGGERED,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        candidate = generator.from_trigger(strong_trigger)
        assert candidate.status == CandidateStatus.ACTIONABLE

        # 中等 -> CANDIDATE
        moderate_trigger = AlphaTrigger(
            trigger_id="moderate_trigger",
            trigger_type=TriggerType.MOMENTUM_SIGNAL,
            asset_code="000001.SH",
            asset_class="a_share金融",
            direction="LONG",
            trigger_condition={},
            invalidation_conditions=[],
            strength=SignalStrength.MODERATE,
            confidence=0.50,
            status=TriggerStatus.TRIGGERED,
            created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )

        candidate = generator.from_trigger(moderate_trigger)
        assert candidate.status == CandidateStatus.CANDIDATE
