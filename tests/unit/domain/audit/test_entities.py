"""
Unit tests for Audit module domain entities.

Tests all dataclasses, enums, and value objects in the domain layer.
Following the principle: Domain layer should have 90%+ test coverage.
"""

import pytest
from datetime import date
from typing import Dict, List
from dataclasses import FrozenInstanceError

from apps.audit.domain.entities import (
    # Enums
    LossSource,
    RegimeTransition,
    ValidationStatus,
    RecommendedAction,
    # Attribution entities
    RegimePeriod,
    PeriodPerformance,
    AttributionResult,
    AttributionConfig,
    # Indicator validation entities
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    ThresholdValidationReport,
    DynamicWeightConfig,
    SignalEvent,
    RegimeSnapshot,
)


class TestLossSource:
    """Test LossSource enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert LossSource.REGIME_TIMING_ERROR.value == "regime_timing"
        assert LossSource.ASSET_SELECTION_ERROR.value == "asset_selection"
        assert LossSource.POLICY_INTERVENTION.value == "policy_intervention"
        assert LossSource.MARKET_VOLATILITY.value == "market_volatility"
        assert LossSource.TRANSACTION_COST.value == "transaction_cost"
        assert LossSource.UNKNOWN.value == "unknown"

    def test_enum_count(self):
        """Test enum has correct number of values."""
        assert len(LossSource) == 6


class TestRegimeTransition:
    """Test RegimeTransition enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert RegimeTransition.SAME.value == "same"
        assert RegimeTransition.CORRECT_PREDICTION.value == "correct_prediction"
        assert RegimeTransition.MISSED_PREDICTION.value == "missed_prediction"
        assert RegimeTransition.WRONG_PREDICTION.value == "wrong_prediction"

    def test_enum_count(self):
        """Test enum has correct number of values."""
        assert len(RegimeTransition) == 4


class TestValidationStatus:
    """Test ValidationStatus enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert ValidationStatus.PENDING.value == "pending"
        assert ValidationStatus.IN_PROGRESS.value == "in_progress"
        assert ValidationStatus.PASSED.value == "passed"
        assert ValidationStatus.FAILED.value == "failed"
        assert ValidationStatus.SHADOW_RUN.value == "shadow_run"

    def test_enum_count(self):
        """Test enum has correct number of values."""
        assert len(ValidationStatus) == 5


class TestRecommendedAction:
    """Test RecommendedAction enum."""

    def test_enum_values(self):
        """Test all enum values exist."""
        assert RecommendedAction.KEEP.value == "keep"
        assert RecommendedAction.INCREASE.value == "increase"
        assert RecommendedAction.DECREASE.value == "decrease"
        assert RecommendedAction.REMOVE.value == "remove"

    def test_enum_count(self):
        """Test enum has correct number of values."""
        assert len(RecommendedAction) == 4


class TestRegimePeriod:
    """Test RegimePeriod dataclass."""

    @pytest.fixture
    def sample_period(self):
        """Create a sample RegimePeriod."""
        return RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            regime="RECOVERY",
            actual_regime="RECOVERY",
            confidence=0.85
        )

    def test_create_regime_period(self, sample_period):
        """Test creating a RegimePeriod."""
        assert sample_period.start_date == date(2024, 1, 1)
        assert sample_period.end_date == date(2024, 3, 31)
        assert sample_period.regime == "RECOVERY"
        assert sample_period.actual_regime == "RECOVERY"
        assert sample_period.confidence == 0.85

    def test_duration_days_property(self, sample_period):
        """Test duration_days property calculation."""
        # Jan 1 to Mar 31 = 90 days (31+29+31 in 2024, leap year)
        assert sample_period.duration_days == 90

    def test_duration_days_single_day(self):
        """Test duration for single day period."""
        period = RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            regime="RECOVERY"
        )
        assert period.duration_days == 0

    def test_frozen_immutable(self, sample_period):
        """Test that RegimePeriod is frozen (immutable)."""
        with pytest.raises(FrozenInstanceError):
            sample_period.confidence = 0.9

    def test_optional_actual_regime(self):
        """Test actual_regime is optional."""
        period = RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            regime="RECOVERY"
        )
        assert period.actual_regime is None

    def test_default_confidence(self):
        """Test default confidence value."""
        period = RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            regime="RECOVERY"
        )
        assert period.confidence == 0.0


class TestPeriodPerformance:
    """Test PeriodPerformance dataclass."""

    @pytest.fixture
    def sample_period(self):
        """Create a sample RegimePeriod."""
        return RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            regime="RECOVERY"
        )

    @pytest.fixture
    def sample_performance(self, sample_period):
        """Create a sample PeriodPerformance."""
        return PeriodPerformance(
            period=sample_period,
            portfolio_return=0.15,
            benchmark_return=0.10,
            best_asset_return=0.25,
            worst_asset_return=-0.05,
            asset_returns={"equity": 0.20, "bond": 0.05, "gold": 0.10}
        )

    def test_create_period_performance(self, sample_performance):
        """Test creating a PeriodPerformance."""
        assert sample_performance.portfolio_return == 0.15
        assert sample_performance.benchmark_return == 0.10
        assert sample_performance.best_asset_return == 0.25
        assert sample_performance.worst_asset_return == -0.05

    def test_asset_returns_dict(self, sample_performance):
        """Test asset_returns dictionary."""
        assert sample_performance.asset_returns["equity"] == 0.20
        assert sample_performance.asset_returns["bond"] == 0.05
        assert sample_performance.asset_returns["gold"] == 0.10

    def test_excess_return_calculation(self, sample_performance):
        """Test calculating excess return."""
        excess = sample_performance.portfolio_return - sample_performance.benchmark_return
        assert abs(excess - 0.05) < 0.001

    def test_frozen_immutable(self, sample_performance):
        """Test that PeriodPerformance is frozen."""
        with pytest.raises(FrozenInstanceError):
            sample_performance.portfolio_return = 0.20


class TestAttributionResult:
    """Test AttributionResult dataclass."""

    @pytest.fixture
    def sample_periods(self):
        """Create sample loss periods."""
        return [
            RegimePeriod(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 2, 28),
                regime="RECOVERY",
                actual_regime="SLOWDOWN"
            )
        ]

    @pytest.fixture
    def sample_attribution(self, sample_periods):
        """Create a sample AttributionResult."""
        return AttributionResult(
            total_return=0.12,
            regime_timing_pnl=0.03,
            asset_selection_pnl=0.06,
            interaction_pnl=0.02,
            transaction_cost_pnl=-0.01,
            loss_source=LossSource.REGIME_TIMING_ERROR,
            loss_amount=-0.02,
            loss_periods=sample_periods,
            lesson_learned="Regime prediction needs improvement",
            improvement_suggestions=["Improve model accuracy", "Add more features"],
            period_attributions=[
                {
                    "period": "2024-01-01 to 2024-02-28",
                    "timing_pnl": 0.01,
                    "selection_pnl": 0.03
                }
            ]
        )

    def test_create_attribution_result(self, sample_attribution):
        """Test creating an AttributionResult."""
        assert sample_attribution.total_return == 0.12
        assert sample_attribution.regime_timing_pnl == 0.03
        assert sample_attribution.asset_selection_pnl == 0.06

    def test_pnl_decomposition(self, sample_attribution):
        """Test PnL decomposition sums to total."""
        expected_total = (
            sample_attribution.regime_timing_pnl +
            sample_attribution.asset_selection_pnl +
            sample_attribution.interaction_pnl +
            sample_attribution.transaction_cost_pnl
        )
        assert expected_total == 0.10  # 0.03 + 0.06 + 0.02 - 0.01

    def test_loss_source(self, sample_attribution):
        """Test loss source is correctly identified."""
        assert sample_attribution.loss_source == LossSource.REGIME_TIMING_ERROR
        assert sample_attribution.loss_amount == -0.02

    def test_lessons_learned(self, sample_attribution):
        """Test lesson learned and suggestions."""
        assert "Regime prediction" in sample_attribution.lesson_learned
        assert len(sample_attribution.improvement_suggestions) == 2

    def test_period_attributions(self, sample_attribution):
        """Test period-level attributions."""
        assert len(sample_attribution.period_attributions) == 1
        assert sample_attribution.period_attributions[0]["timing_pnl"] == 0.01


class TestAttributionConfig:
    """Test AttributionConfig dataclass."""

    def test_default_config(self):
        """Test creating config with default values."""
        config = AttributionConfig()
        assert config.risk_free_rate == 0.03
        assert config.benchmark_return == 0.08
        assert config.min_confidence_threshold == 0.3

    def test_custom_config(self):
        """Test creating config with custom values."""
        config = AttributionConfig(
            risk_free_rate=0.025,
            benchmark_return=0.10,
            min_confidence_threshold=0.5
        )
        assert config.risk_free_rate == 0.025
        assert config.benchmark_return == 0.10
        assert config.min_confidence_threshold == 0.5

    def test_frozen_immutable(self):
        """Test that AttributionConfig is frozen."""
        config = AttributionConfig()
        with pytest.raises(FrozenInstanceError):
            config.risk_free_rate = 0.04


class TestIndicatorPerformanceReport:
    """Test IndicatorPerformanceReport dataclass."""

    @pytest.fixture
    def sample_report(self):
        """Create a sample IndicatorPerformanceReport."""
        return IndicatorPerformanceReport(
            indicator_code="CN_PMI",
            evaluation_period_start=date(2023, 1, 1),
            evaluation_period_end=date(2024, 12, 31),
            true_positive_count=45,
            false_positive_count=10,
            true_negative_count=120,
            false_negative_count=15,
            precision=0.818,
            recall=0.75,
            f1_score=0.783,
            accuracy=0.873,
            lead_time_mean=1.5,
            lead_time_std=0.8,
            pre_2015_correlation=0.65,
            post_2015_correlation=0.72,
            stability_score=0.68,
            recommended_action="KEEP",
            recommended_weight=1.0,
            confidence_level=0.85,
            decay_rate=0.15,
            signal_strength=0.70
        )

    def test_create_performance_report(self, sample_report):
        """Test creating an IndicatorPerformanceReport."""
        assert sample_report.indicator_code == "CN_PMI"
        assert sample_report.f1_score == 0.783

    def test_confusion_matrix_totals(self, sample_report):
        """Test confusion matrix totals."""
        total = (
            sample_report.true_positive_count +
            sample_report.false_positive_count +
            sample_report.true_negative_count +
            sample_report.false_negative_count
        )
        assert total == 190  # 45 + 10 + 120 + 15

    def test_evaluation_period(self, sample_report):
        """Test evaluation period."""
        assert sample_report.evaluation_period_start == date(2023, 1, 1)
        assert sample_report.evaluation_period_end == date(2024, 12, 31)

    def test_lead_time_metrics(self, sample_report):
        """Test lead time metrics."""
        assert sample_report.lead_time_mean == 1.5
        assert sample_report.lead_time_std == 0.8

    def test_stability_metrics(self, sample_report):
        """Test stability metrics."""
        assert sample_report.pre_2015_correlation == 0.65
        assert sample_report.post_2015_correlation == 0.72
        assert sample_report.stability_score == 0.68

    def test_recommended_action(self, sample_report):
        """Test recommended action."""
        assert sample_report.recommended_action == "KEEP"
        assert sample_report.recommended_weight == 1.0
        assert sample_report.confidence_level == 0.85

    def test_signal_features(self, sample_report):
        """Test signal decay and strength features."""
        assert sample_report.decay_rate == 0.15
        assert sample_report.signal_strength == 0.70


class TestIndicatorThresholdConfig:
    """Test IndicatorThresholdConfig dataclass."""

    def test_create_threshold_config(self):
        """Test creating an IndicatorThresholdConfig."""
        config = IndicatorThresholdConfig(
            indicator_code="CN_PMI",
            indicator_name="PMI",
            level_low=49.0,
            level_high=51.0
        )
        assert config.indicator_code == "CN_PMI"
        assert config.level_low == 49.0
        assert config.level_high == 51.0

    def test_default_weight_values(self):
        """Test default weight configuration."""
        config = IndicatorThresholdConfig(
            indicator_code="CN_CPI",
            indicator_name="CPI",
            level_low=2.0,
            level_high=3.0
        )
        assert config.base_weight == 1.0
        assert config.min_weight == 0.0
        assert config.max_weight == 1.0

    def test_default_validation_thresholds(self):
        """Test default validation thresholds."""
        config = IndicatorThresholdConfig(
            indicator_code="CN_GDP",
            indicator_name="GDP",
            level_low=5.5,
            level_high=6.5
        )
        assert config.decay_threshold == 0.2
        assert config.decay_penalty == 0.5
        assert config.improvement_threshold == 0.1
        assert config.improvement_bonus == 1.2

    def test_default_action_thresholds(self):
        """Test default action thresholds."""
        config = IndicatorThresholdConfig(
            indicator_code="CN_RFI",
            indicator_name="Retail Sales",
            level_low=8.0,
            level_high=12.0
        )
        assert config.keep_min_f1 == 0.6
        assert config.reduce_min_f1 == 0.4
        assert config.remove_max_f1 == 0.3

    def test_custom_thresholds(self):
        """Test custom threshold values."""
        config = IndicatorThresholdConfig(
            indicator_code="CN_PMI",
            indicator_name="PMI",
            level_low=48.0,
            level_high=52.0,
            base_weight=1.5,
            keep_min_f1=0.7
        )
        assert config.base_weight == 1.5
        assert config.keep_min_f1 == 0.7


class TestThresholdValidationReport:
    """Test ThresholdValidationReport dataclass."""

    @pytest.fixture
    def sample_indicator_reports(self):
        """Create sample indicator reports."""
        return [
            IndicatorPerformanceReport(
                indicator_code="CN_PMI",
                evaluation_period_start=date(2023, 1, 1),
                evaluation_period_end=date(2024, 12, 31),
                true_positive_count=45,
                false_positive_count=10,
                true_negative_count=120,
                false_negative_count=15,
                precision=0.818,
                recall=0.75,
                f1_score=0.783,
                accuracy=0.873,
                lead_time_mean=1.5,
                lead_time_std=0.8,
                pre_2015_correlation=0.65,
                post_2015_correlation=0.72,
                stability_score=0.68,
                recommended_action="KEEP",
                recommended_weight=1.0,
                confidence_level=0.85
            ),
            IndicatorPerformanceReport(
                indicator_code="CN_CPI",
                evaluation_period_start=date(2023, 1, 1),
                evaluation_period_end=date(2024, 12, 31),
                true_positive_count=30,
                false_positive_count=20,
                true_negative_count=110,
                false_negative_count=30,
                precision=0.60,
                recall=0.50,
                f1_score=0.545,
                accuracy=0.684,
                lead_time_mean=1.0,
                lead_time_std=1.2,
                pre_2015_correlation=0.40,
                post_2015_correlation=0.45,
                stability_score=0.42,
                recommended_action="DECREASE",
                recommended_weight=0.5,
                confidence_level=0.60
            )
        ]

    @pytest.fixture
    def sample_validation_report(self, sample_indicator_reports):
        """Create a sample ThresholdValidationReport."""
        return ThresholdValidationReport(
            validation_run_id="val_20240101",
            run_date=date(2024, 1, 1),
            evaluation_period_start=date(2023, 1, 1),
            evaluation_period_end=date(2024, 12, 31),
            total_indicators=2,
            approved_indicators=1,
            rejected_indicators=0,
            pending_indicators=1,
            indicator_reports=sample_indicator_reports,
            overall_recommendation="Review CN_CPI threshold settings",
            status=ValidationStatus.PASSED
        )

    def test_create_validation_report(self, sample_validation_report):
        """Test creating a ThresholdValidationReport."""
        assert sample_validation_report.validation_run_id == "val_20240101"
        assert sample_validation_report.total_indicators == 2

    def test_indicator_counts(self, sample_validation_report):
        """Test indicator status counts."""
        assert sample_validation_report.approved_indicators == 1
        assert sample_validation_report.rejected_indicators == 0
        assert sample_validation_report.pending_indicators == 1
        # Total should match sum of statuses
        assert (
            sample_validation_report.approved_indicators +
            sample_validation_report.rejected_indicators +
            sample_validation_report.pending_indicators
        ) == sample_validation_report.total_indicators

    def test_indicator_reports_list(self, sample_validation_report):
        """Test list of indicator reports."""
        assert len(sample_validation_report.indicator_reports) == 2
        assert sample_validation_report.indicator_reports[0].indicator_code == "CN_PMI"
        assert sample_validation_report.indicator_reports[1].indicator_code == "CN_CPI"

    def test_overall_recommendation(self, sample_validation_report):
        """Test overall recommendation."""
        assert "CN_CPI" in sample_validation_report.overall_recommendation

    def test_validation_status(self, sample_validation_report):
        """Test validation status."""
        assert sample_validation_report.status == ValidationStatus.PASSED


class TestDynamicWeightConfig:
    """Test DynamicWeightConfig dataclass."""

    def test_create_dynamic_weight_config(self):
        """Test creating a DynamicWeightConfig."""
        config = DynamicWeightConfig(
            indicator_code="CN_PMI",
            current_weight=1.2,
            original_weight=1.0,
            f1_score=0.85,
            stability_score=0.80,
            decay_rate=0.10,
            adjustment_factor=1.2,
            new_weight=1.2,
            reason="High F1 score and stability",
            confidence=0.90
        )
        assert config.indicator_code == "CN_PMI"
        assert config.new_weight > config.original_weight

    def test_weight_adjustment(self):
        """Test weight adjustment calculation."""
        config = DynamicWeightConfig(
            indicator_code="CN_PMI",
            current_weight=1.0,
            original_weight=1.0,
            f1_score=0.5,
            stability_score=0.4,
            decay_rate=0.3,
            adjustment_factor=0.7,
            new_weight=0.7,
            reason="Low performance metrics",
            confidence=0.70
        )
        assert config.new_weight < config.original_weight
        assert config.adjustment_factor == 0.7


class TestSignalEvent:
    """Test SignalEvent dataclass."""

    def test_create_signal_event(self):
        """Test creating a SignalEvent."""
        event = SignalEvent(
            indicator_code="CN_PMI",
            signal_date=date(2024, 1, 15),
            signal_type="BULLISH",
            signal_value=51.5,
            threshold_used=51.0,
            confidence=0.85
        )
        assert event.indicator_code == "CN_PMI"
        assert event.signal_type == "BULLISH"
        assert event.signal_value > event.threshold_used

    def test_bearish_signal(self):
        """Test bearish signal."""
        event = SignalEvent(
            indicator_code="CN_PMI",
            signal_date=date(2024, 1, 15),
            signal_type="BEARISH",
            signal_value=48.5,
            threshold_used=49.0,
            confidence=0.75
        )
        assert event.signal_type == "BEARISH"
        assert event.signal_value < event.threshold_used

    def test_neutral_signal(self):
        """Test neutral signal."""
        event = SignalEvent(
            indicator_code="CN_PMI",
            signal_date=date(2024, 1, 15),
            signal_type="NEUTRAL",
            signal_value=50.0,
            threshold_used=49.0,
            confidence=0.50
        )
        assert event.signal_type == "NEUTRAL"


class TestRegimeSnapshot:
    """Test RegimeSnapshot dataclass."""

    @pytest.fixture
    def sample_snapshot(self):
        """Create a sample RegimeSnapshot."""
        return RegimeSnapshot(
            observed_at=date(2024, 1, 15),
            dominant_regime="RECOVERY",
            confidence=0.85,
            growth_momentum_z=1.5,
            inflation_momentum_z=0.8,
            distribution={
                "RECOVERY": 0.70,
                "OVERHEAT": 0.15,
                "SLOWDOWN": 0.10,
                "STAGFLATION": 0.05
            }
        )

    def test_create_regime_snapshot(self, sample_snapshot):
        """Test creating a RegimeSnapshot."""
        assert sample_snapshot.dominant_regime == "RECOVERY"
        assert sample_snapshot.confidence == 0.85

    def test_momentum_z_scores(self, sample_snapshot):
        """Test momentum z-scores."""
        assert sample_snapshot.growth_momentum_z == 1.5
        assert sample_snapshot.inflation_momentum_z == 0.8

    def test_distribution_probabilities(self, sample_snapshot):
        """Test regime distribution probabilities."""
        total_prob = sum(sample_snapshot.distribution.values())
        assert abs(total_prob - 1.0) < 0.01  # Should sum to ~1.0

    def test_dominant_regime_matches_distribution(self, sample_snapshot):
        """Test dominant regime has highest probability."""
        dominant_prob = sample_snapshot.distribution[sample_snapshot.dominant_regime]
        for regime, prob in sample_snapshot.distribution.items():
            if regime != sample_snapshot.dominant_regime:
                assert dominant_prob > prob


class TestEntityCombinations:
    """Test entities working together."""

    def test_attribution_with_periods(self):
        """Test AttributionResult with RegimePeriod."""
        loss_period = RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 28),
            regime="RECOVERY",
            actual_regime="SLOWDOWN",
            confidence=0.5
        )
        attribution = AttributionResult(
            total_return=-0.02,
            regime_timing_pnl=-0.03,
            asset_selection_pnl=0.01,
            interaction_pnl=0.0,
            transaction_cost_pnl=0.0,
            loss_source=LossSource.REGIME_TIMING_ERROR,
            loss_amount=-0.02,
            loss_periods=[loss_period],
            lesson_learned="Low confidence prediction",
            improvement_suggestions=["Improve confidence scoring"],
            period_attributions=[
                {
                    "period": "2024-01-01 to 2024-02-28",
                    "timing_pnl": -0.03,
                    "regime": "RECOVERY",
                    "actual_regime": "SLOWDOWN"
                }
            ]
        )
        assert len(attribution.loss_periods) == 1
        assert attribution.loss_periods[0].confidence == 0.5

    def test_performance_report_with_signal_events(self):
        """Test IndicatorPerformanceReport context with SignalEvents."""
        # Create signal events that would generate the report
        signal_event = SignalEvent(
            indicator_code="CN_PMI",
            signal_date=date(2024, 1, 15),
            signal_type="BULLISH",
            signal_value=51.5,
            threshold_used=51.0,
            confidence=0.85
        )
        # Report would be generated from analyzing signal events
        assert signal_event.indicator_code == "CN_PMI"
