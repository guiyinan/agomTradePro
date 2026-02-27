"""
Unit tests for Policy domain rules.

Tests the core business logic for gate levels and auto-approval.
"""

import pytest
from datetime import datetime, timezone, timedelta

from apps.policy.domain.entities import (
    PolicyLevel,
    EventType,
    GateLevel,
    SentimentGateThresholds,
    IngestionConfig,
)
from apps.policy.domain.rules import (
    calculate_gate_level,
    should_auto_approve,
    normalize_sentiment_score,
    is_sla_exceeded,
    get_max_position_cap,
    can_event_affect_policy_level,
    should_event_count_in_gate,
)


class TestCalculateGateLevel:
    """Tests for calculate_gate_level function."""

    @pytest.fixture
    def thresholds(self):
        return SentimentGateThresholds(
            heat_l1_threshold=30.0,
            heat_l2_threshold=60.0,
            heat_l3_threshold=85.0,
            sentiment_l1_threshold=-0.3,
            sentiment_l2_threshold=-0.6,
            sentiment_l3_threshold=-0.8,
        )

    def test_no_data_returns_l0(self, thresholds):
        """When no heat or sentiment data, return L0."""
        result = calculate_gate_level(None, None, thresholds)
        assert result == GateLevel.L0

    def test_l3_triggered_by_high_heat(self, thresholds):
        """Heat at or above L3 threshold triggers L3."""
        result = calculate_gate_level(85.0, None, thresholds)
        assert result == GateLevel.L3

        result = calculate_gate_level(90.0, 0.5, thresholds)
        assert result == GateLevel.L3

    def test_l3_triggered_by_negative_sentiment(self, thresholds):
        """Sentiment at or below L3 threshold triggers L3."""
        result = calculate_gate_level(None, -0.8, thresholds)
        assert result == GateLevel.L3

        result = calculate_gate_level(20.0, -0.9, thresholds)
        assert result == GateLevel.L3

    def test_l2_triggered_by_heat(self, thresholds):
        """Heat at L2 threshold but below L3 triggers L2."""
        result = calculate_gate_level(60.0, None, thresholds)
        assert result == GateLevel.L2

        result = calculate_gate_level(70.0, 0.0, thresholds)
        assert result == GateLevel.L2

    def test_l2_triggered_by_sentiment(self, thresholds):
        """Sentiment at L2 threshold but above L3 triggers L2."""
        result = calculate_gate_level(None, -0.6, thresholds)
        assert result == GateLevel.L2

        result = calculate_gate_level(10.0, -0.7, thresholds)
        assert result == GateLevel.L2

    def test_l1_triggered_by_heat(self, thresholds):
        """Heat at L1 threshold but below L2 triggers L1."""
        result = calculate_gate_level(30.0, None, thresholds)
        assert result == GateLevel.L1

        result = calculate_gate_level(50.0, 0.5, thresholds)
        assert result == GateLevel.L1

    def test_l1_triggered_by_sentiment(self, thresholds):
        """Sentiment at L1 threshold but above L2 triggers L1."""
        result = calculate_gate_level(None, -0.3, thresholds)
        assert result == GateLevel.L1

        result = calculate_gate_level(10.0, -0.4, thresholds)
        assert result == GateLevel.L1

    def test_normal_returns_l0(self, thresholds):
        """Normal heat and sentiment returns L0."""
        result = calculate_gate_level(20.0, 0.5, thresholds)
        assert result == GateLevel.L0

        result = calculate_gate_level(15.0, 0.0, thresholds)
        assert result == GateLevel.L0

    def test_heat_overrides_sentiment_for_higher_level(self, thresholds):
        """Higher severity from heat takes precedence."""
        # Heat L2, sentiment L1 -> should be L2
        result = calculate_gate_level(65.0, -0.4, thresholds)
        assert result == GateLevel.L2


class TestShouldAutoApprove:
    """Tests for should_auto_approve function."""

    @pytest.fixture
    def config_enabled(self):
        return IngestionConfig(
            auto_approve_enabled=True,
            auto_approve_min_level=PolicyLevel.P2,
            auto_approve_threshold=0.85,
            p23_sla_hours=2,
            normal_sla_hours=24,
        )

    @pytest.fixture
    def config_disabled(self):
        return IngestionConfig(
            auto_approve_enabled=False,
            auto_approve_min_level=PolicyLevel.P2,
            auto_approve_threshold=0.85,
            p23_sla_hours=2,
            normal_sla_hours=24,
        )

    def test_auto_approve_disabled(self, config_disabled):
        """When auto-approve is disabled, always return False."""
        approved, reason = should_auto_approve(PolicyLevel.P2, 0.95, config_disabled)
        assert approved is False
        assert "未启用" in reason

    def test_no_confidence_returns_false(self, config_enabled):
        """When no AI confidence, return False."""
        approved, reason = should_auto_approve(PolicyLevel.P2, None, config_enabled)
        assert approved is False
        assert "缺少" in reason

    def test_low_confidence_returns_false(self, config_enabled):
        """When confidence below threshold, return False."""
        approved, reason = should_auto_approve(PolicyLevel.P2, 0.80, config_enabled)
        assert approved is False
        assert "低于阈值" in reason

    def test_p2_high_confidence_approved(self, config_enabled):
        """P2 with high confidence should be approved."""
        approved, reason = should_auto_approve(PolicyLevel.P2, 0.90, config_enabled)
        assert approved is True
        assert "满足" in reason

    def test_p3_high_confidence_approved(self, config_enabled):
        """P3 with high confidence should be approved."""
        approved, reason = should_auto_approve(PolicyLevel.P3, 0.95, config_enabled)
        assert approved is True

    def test_p1_high_confidence_not_approved(self, config_enabled):
        """P1 should not be auto-approved when min level is P2."""
        approved, reason = should_auto_approve(PolicyLevel.P1, 0.95, config_enabled)
        assert approved is False
        assert "低于自动生效最低档位" in reason

    def test_p0_high_confidence_not_approved(self, config_enabled):
        """P0 should not be auto-approved when min level is P2."""
        approved, reason = should_auto_approve(PolicyLevel.P0, 0.95, config_enabled)
        assert approved is False

    def test_threshold_boundary(self, config_enabled):
        """At exact threshold, should be approved."""
        approved, reason = should_auto_approve(PolicyLevel.P2, 0.85, config_enabled)
        assert approved is True


class TestNormalizeSentimentScore:
    """Tests for normalize_sentiment_score function."""

    def test_default_range_middle(self):
        """Middle of default range (-3, 3) should be 0."""
        result = normalize_sentiment_score(0.0)
        assert result == pytest.approx(0.0, abs=0.01)

    def test_default_range_max(self):
        """Max of default range should be 1.0."""
        result = normalize_sentiment_score(3.0)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_default_range_min(self):
        """Min of default range should be -1.0."""
        result = normalize_sentiment_score(-3.0)
        assert result == pytest.approx(-1.0, abs=0.01)

    def test_custom_range(self):
        """Custom range should work correctly."""
        result = normalize_sentiment_score(5.0, score_range=(0, 10))
        assert result == pytest.approx(0.0, abs=0.01)

        result = normalize_sentiment_score(10.0, score_range=(0, 10))
        assert result == pytest.approx(1.0, abs=0.01)

    def test_clamping_high(self):
        """Values above range should be clamped to 1.0."""
        result = normalize_sentiment_score(5.0, score_range=(-3, 3))
        assert result == 1.0

    def test_clamping_low(self):
        """Values below range should be clamped to -1.0."""
        result = normalize_sentiment_score(-5.0, score_range=(-3, 3))
        assert result == -1.0


class TestIsSlaExceeded:
    """Tests for is_sla_exceeded function."""

    @pytest.fixture
    def config(self):
        return IngestionConfig(
            auto_approve_enabled=True,
            auto_approve_min_level=PolicyLevel.P2,
            auto_approve_threshold=0.85,
            p23_sla_hours=2,
            normal_sla_hours=24,
        )

    def test_p2_within_sla(self, config):
        """P2 event within 2-hour SLA should not be exceeded."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(hours=1)

        exceeded, hours = is_sla_exceeded(created_at, PolicyLevel.P2, config, now)
        assert exceeded is False
        assert hours == 0

    def test_p2_exceeded_sla(self, config):
        """P2 event past 2-hour SLA should be exceeded."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(hours=3)

        exceeded, hours = is_sla_exceeded(created_at, PolicyLevel.P2, config, now)
        assert exceeded is True
        assert hours == 1

    def test_p3_within_sla(self, config):
        """P3 event within 2-hour SLA should not be exceeded."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(hours=1.5)

        exceeded, hours = is_sla_exceeded(created_at, PolicyLevel.P3, config, now)
        assert exceeded is False

    def test_p0_within_sla(self, config):
        """P0 event within 24-hour SLA should not be exceeded."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(hours=12)

        exceeded, hours = is_sla_exceeded(created_at, PolicyLevel.P0, config, now)
        assert exceeded is False

    def test_p0_exceeded_sla(self, config):
        """P0 event past 24-hour SLA should be exceeded."""
        now = datetime.now(timezone.utc)
        created_at = now - timedelta(hours=26)

        exceeded, hours = is_sla_exceeded(created_at, PolicyLevel.P0, config, now)
        assert exceeded is True
        assert hours == 2


class TestGetMaxPositionCap:
    """Tests for get_max_position_cap function."""

    def test_l3_cap(self):
        """L3 should return L3 cap."""
        config = {'max_position_cap_l2': 0.7, 'max_position_cap_l3': 0.3}
        result = get_max_position_cap(GateLevel.L3, config)
        assert result == 0.3

    def test_l2_cap(self):
        """L2 should return L2 cap."""
        config = {'max_position_cap_l2': 0.7, 'max_position_cap_l3': 0.3}
        result = get_max_position_cap(GateLevel.L2, config)
        assert result == 0.7

    def test_l1_no_cap(self):
        """L1 should return 1.0 (no cap)."""
        config = {'max_position_cap_l2': 0.7, 'max_position_cap_l3': 0.3}
        result = get_max_position_cap(GateLevel.L1, config)
        assert result == 1.0

    def test_l0_no_cap(self):
        """L0 should return 1.0 (no cap)."""
        config = {'max_position_cap_l2': 0.7, 'max_position_cap_l3': 0.3}
        result = get_max_position_cap(GateLevel.L0, config)
        assert result == 1.0


class TestCanEventAffectPolicyLevel:
    """Tests for can_event_affect_policy_level function."""

    def test_policy_events_affect_policy_level(self):
        """Policy events should affect P0-P3."""
        assert can_event_affect_policy_level(EventType.POLICY) is True

    def test_hotspot_events_do_not_affect_policy_level(self):
        """Hotspot events should NOT affect P0-P3."""
        assert can_event_affect_policy_level(EventType.HOTSPOT) is False

    def test_sentiment_events_do_not_affect_policy_level(self):
        """Sentiment events should NOT affect P0-P3."""
        assert can_event_affect_policy_level(EventType.SENTIMENT) is False

    def test_mixed_events_do_not_affect_policy_level(self):
        """Mixed events should NOT affect P0-P3."""
        assert can_event_affect_policy_level(EventType.MIXED) is False


class TestShouldEventCountInGate:
    """Tests for should_event_count_in_gate function."""

    def test_effective_hotspot_counts(self):
        """Effective hotspot events should count in gate."""
        assert should_event_count_in_gate(EventType.HOTSPOT, True) is True

    def test_effective_sentiment_counts(self):
        """Effective sentiment events should count in gate."""
        assert should_event_count_in_gate(EventType.SENTIMENT, True) is True

    def test_effective_mixed_counts(self):
        """Effective mixed events should count in gate."""
        assert should_event_count_in_gate(EventType.MIXED, True) is True

    def test_non_effective_does_not_count(self):
        """Non-effective events should NOT count in gate."""
        assert should_event_count_in_gate(EventType.HOTSPOT, False) is False
        assert should_event_count_in_gate(EventType.SENTIMENT, False) is False

    def test_policy_events_do_not_count_in_gate(self):
        """Policy events should NOT count in gate (they affect P level instead)."""
        assert should_event_count_in_gate(EventType.POLICY, True) is False
