"""
Unit Tests for Phase 4: Probability Confidence Model.

Tests for:
- Confidence calculation
- Bayesian confidence
- Signal conflict resolution
- Dynamic weight calculation
"""



from apps.regime.domain.entities import (
    ConfidenceBreakdown,
    ConfidenceConfig,
    IndicatorPredictivePower,
    RegimeProbabilities,
    SignalConflict,
)
from apps.regime.domain.services import (
    ConfidenceCalculator,
    calculate_bayesian_confidence,
    calculate_confidence,
    calculate_dynamic_weight,
    resolve_signal_conflict,
)


class TestConfidenceCalculation:
    """Test confidence calculation functions"""

    def test_calculate_confidence_default_config(self):
        """Test confidence calculation with default config"""
        result = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=False,
        )

        assert isinstance(result, ConfidenceBreakdown)
        assert 0 <= result.total_confidence <= 1
        assert result.days_since_last_update == 1
        assert not result.has_daily_data
        assert not result.daily_consistent

    def test_calculate_confidence_fresh_data(self):
        """Test fresh data (day 0) has higher confidence"""
        result_fresh = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=False,
        )

        result_stale = calculate_confidence(
            base_confidence=0.5,
            days_since_update=30,
            has_daily_data=False,
        )

        assert result_fresh.total_confidence > result_stale.total_confidence

    def test_calculate_confidence_with_daily_data(self):
        """Test daily data bonus increases confidence"""
        result_no_daily = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=False,
        )

        result_with_daily = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=True,
        )

        assert result_with_daily.total_confidence > result_no_daily.total_confidence
        assert result_with_daily.data_freshness_component > 0

    def test_calculate_confidence_with_consistency(self):
        """Test daily consistency bonus increases confidence"""
        result_not_consistent = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=True,
            daily_consistent=False,
        )

        result_consistent = calculate_confidence(
            base_confidence=0.5,
            days_since_update=1,
            has_daily_data=True,
            daily_consistent=True,
        )

        assert result_consistent.total_confidence > result_not_consistent.total_confidence

    def test_calculate_confidence_custom_config(self):
        """Test confidence calculation with custom config"""
        custom_config = ConfidenceConfig(
            day_0_coefficient=0.8,
            day_7_coefficient=0.7,
            day_14_coefficient=0.6,
            day_30_coefficient=0.5,
            daily_data_bonus=0.3,
            weekly_data_bonus=0.15,
            daily_consistency_bonus=0.15,
            base_confidence=0.6,
        )

        result = calculate_confidence(
            base_confidence=0.6,
            days_since_update=1,
            has_daily_data=True,
            config=custom_config,
        )

        assert result.total_confidence > 0.6  # Should be higher due to bonuses

    def test_confidence_breakdown_to_dict(self):
        """Test ConfidenceBreakdown.to_dict()"""
        result = calculate_confidence(
            base_confidence=0.5,
            days_since_update=5,
            has_daily_data=True,
            daily_consistent=True,
        )

        result_dict = result.to_dict()

        assert isinstance(result_dict, dict)
        assert 'total_confidence' in result_dict
        assert 'data_freshness_component' in result_dict
        assert 'predictive_power_component' in result_dict
        assert 'consistency_component' in result_dict
        assert 'base_component' in result_dict
        assert result_dict['total_confidence'] == result.total_confidence


class TestBayesianConfidence:
    """Test Bayesian confidence calculation"""

    def test_empty_indicators_returns_uniform(self):
        """Test empty indicators returns uniform distribution"""
        result = calculate_bayesian_confidence(
            indicators=[],
            base_prior=0.5,
        )

        assert isinstance(result, RegimeProbabilities)
        assert result.growth_reflation == 0.25
        assert result.growth_disinflation == 0.25
        assert result.stagnation_reflation == 0.25
        assert result.stagnation_disinflation == 0.25
        assert result.confidence == 0.5

    def test_single_bullish_indicator(self):
        """Test single bullish indicator increases bullish probabilities"""
        indicator = IndicatorPredictivePower(
            indicator_code='TEST_BULLISH',
            true_positive_rate=0.8,
            false_positive_rate=0.1,
            precision=0.9,
            f1_score=0.85,
            lead_time_mean=6.0,
            lead_time_std=2.0,
            lead_time_min=3.0,
            lead_time_max=12.0,
            pre_2015_correlation=0.5,
            post_2015_correlation=0.6,
            stability_score=0.8,
            current_signal='BULLISH',
            signal_strength=0.8,
            days_since_last_update=3,
            base_weight=1.0,
            current_weight=1.0,
        )

        result = calculate_bayesian_confidence(
            indicators=[indicator],
            base_prior=0.5,
        )

        # Bullish should increase Recovery and Overheat
        assert result.growth_disinflation > 0 or result.growth_reflation > 0
        assert result.confidence >= 0.5  # Should be at least base prior

    def test_multiple_indicators_weighting(self):
        """Test multiple indicators are weighted by predictive power"""
        strong_indicator = IndicatorPredictivePower(
            indicator_code='STRONG',
            true_positive_rate=0.9,
            false_positive_rate=0.05,
            precision=0.95,
            f1_score=0.92,
            lead_time_mean=6.0,
            lead_time_std=2.0,
            lead_time_min=3.0,
            lead_time_max=12.0,
            pre_2015_correlation=0.7,
            post_2015_correlation=0.75,
            stability_score=0.9,
            current_signal='BULLISH',
            signal_strength=0.9,
            days_since_last_update=1,
            base_weight=1.0,
            current_weight=1.0,
        )

        weak_indicator = IndicatorPredictivePower(
            indicator_code='WEAK',
            true_positive_rate=0.6,
            false_positive_rate=0.3,
            precision=0.7,
            f1_score=0.65,
            lead_time_mean=4.0,
            lead_time_std=3.0,
            lead_time_min=1.0,
            lead_time_max=10.0,
            pre_2015_correlation=0.3,
            post_2015_correlation=0.4,
            stability_score=0.5,
            current_signal='BEARISH',
            signal_strength=0.5,
            days_since_last_update=10,
            base_weight=1.0,
            current_weight=1.0,
        )

        result = calculate_bayesian_confidence(
            indicators=[strong_indicator, weak_indicator],
            base_prior=0.5,
        )

        # Strong bullish should outweigh weak bearish
        assert result.growth_disinflation > result.stagnation_disinflation
        assert result.growth_reflation > result.stagnation_reflation

    def test_regime_probabilities_normalize(self):
        """Test RegimeProbabilities.normalize()"""
        probs = RegimeProbabilities(
            growth_reflation=0.5,
            growth_disinflation=0.3,
            stagnation_reflation=0.15,
            stagnation_disinflation=0.05,
            confidence=0.7,
            data_freshness_score=0.8,
            predictive_power_score=0.75,
            consistency_score=0.9,
        )

        normalized = probs.normalize()

        # Sum should be 1.0
        total = (normalized.growth_reflation +
                 normalized.growth_disinflation +
                 normalized.stagnation_reflation +
                 normalized.stagnation_disinflation)
        assert abs(total - 1.0) < 0.001

    def test_regime_probabilities_distribution(self):
        """Test RegimeProbabilities.distribution property"""
        probs = RegimeProbabilities(
            growth_reflation=0.3,
            growth_disinflation=0.3,
            stagnation_reflation=0.2,
            stagnation_disinflation=0.2,
            confidence=0.7,
            data_freshness_score=0.8,
            predictive_power_score=0.75,
            consistency_score=0.9,
        )

        dist = probs.distribution

        assert isinstance(dist, dict)
        assert 'Overheat' in dist
        assert 'Recovery' in dist
        assert 'Stagflation' in dist
        assert 'Deflation' in dist
        assert dist['Overheat'] == 0.3
        assert dist['Recovery'] == 0.3

    def test_indicator_predictive_power_properties(self):
        """Test IndicatorPredictivePower calculated properties"""
        indicator = IndicatorPredictivePower(
            indicator_code='TEST',
            true_positive_rate=0.8,
            false_positive_rate=0.1,
            precision=0.9,
            f1_score=0.85,
            lead_time_mean=6.0,
            lead_time_std=2.0,
            lead_time_min=3.0,
            lead_time_max=12.0,
            pre_2015_correlation=0.5,
            post_2015_correlation=0.6,
            stability_score=0.8,
            current_signal='BULLISH',
            signal_strength=0.8,
            days_since_last_update=3,
            base_weight=1.0,
            current_weight=1.0,
        )

        # Test predictive_power_score
        expected_score = 0.85 * 0.7 + 0.8 * 0.3
        assert abs(indicator.predictive_power_score - expected_score) < 0.001

        # Test reliability_score
        expected_reliability = 0.8 * 0.6 + (1 - 0.1) * 0.4
        assert abs(indicator.reliability_score - expected_reliability) < 0.001

        # Test is_decay_detected
        assert not indicator.is_decay_detected

        decayed_indicator = IndicatorPredictivePower(
            indicator_code='DECAYED',
            true_positive_rate=0.5,
            false_positive_rate=0.3,
            precision=0.6,
            f1_score=0.55,
            lead_time_mean=4.0,
            lead_time_std=3.0,
            lead_time_min=1.0,
            lead_time_max=10.0,
            pre_2015_correlation=0.3,
            post_2015_correlation=0.2,
            stability_score=0.4,
            current_signal='NEUTRAL',
            signal_strength=0.3,
            days_since_last_update=30,
            base_weight=1.0,
            current_weight=0.5,  # Weight reduced to 50%
        )
        assert decayed_indicator.is_decay_detected


class TestSignalConflictResolution:
    """Test signal conflict resolution"""

    def test_all_consistent(self):
        """Test when daily and monthly signals agree"""
        result = resolve_signal_conflict(
            daily_signal='Recovery',
            weekly_signal=None,
            monthly_signal='Recovery',
            daily_confidence=0.7,
            monthly_confidence=0.6,
            daily_duration=5,
        )

        assert result.resolution_source == 'ALL_CONSISTENT'
        assert result.final_signal == 'Recovery'
        assert result.final_confidence > 0.6  # Should be boosted

    def test_daily_persistent(self):
        """Test daily signal overrides when persistent"""
        result = resolve_signal_conflict(
            daily_signal='Overheat',
            weekly_signal=None,
            monthly_signal='Deflation',
            daily_confidence=0.6,
            monthly_confidence=0.7,
            daily_duration=12,  # Above threshold
        )

        assert result.resolution_source == 'DAILY_PERSISTENT'
        assert result.final_signal == 'Overheat'

    def test_daily_weekly_consistent(self):
        """Test daily+weekly consistency overrides monthly"""
        result = resolve_signal_conflict(
            daily_signal='Stagflation',
            weekly_signal='Stagflation',
            monthly_signal='Recovery',
            daily_confidence=0.6,
            monthly_confidence=0.7,
            daily_duration=5,
        )

        assert result.resolution_source == 'DAILY_WEEKLY_CONSISTENT'
        assert result.final_signal == 'Stagflation'

    def test_monthly_default(self):
        """Test default to monthly when signals conflict"""
        result = resolve_signal_conflict(
            daily_signal='Overheat',
            weekly_signal=None,
            monthly_signal='Deflation',
            daily_confidence=0.6,
            monthly_confidence=0.7,
            daily_duration=5,  # Below threshold
        )

        assert result.resolution_source == 'MONTHLY_DEFAULT'
        assert result.final_signal == 'Deflation'
        assert result.final_confidence < 0.7  # Should be reduced

    def test_regime_direction_mapping(self):
        """Test regime direction is correctly mapped"""
        # Both bullish (Recovery + Overheat)
        result = resolve_signal_conflict(
            daily_signal='Overheat',
            weekly_signal='Recovery',
            monthly_signal='Overheat',
            daily_confidence=0.6,
            monthly_confidence=0.7,
            daily_duration=5,
        )

        assert result.resolution_source == 'ALL_CONSISTENT'

        # Opposing directions
        result = resolve_signal_conflict(
            daily_signal='Stagflation',
            weekly_signal='Deflation',
            monthly_signal='Recovery',
            daily_confidence=0.6,
            monthly_confidence=0.7,
            daily_duration=5,
        )

        assert result.resolution_source == 'DAILY_WEEKLY_CONSISTENT'


class TestDynamicWeightCalculation:
    """Test dynamic weight calculation"""

    def test_baseline_weight(self):
        """Test baseline weight with good F1 score"""
        weight = calculate_dynamic_weight(
            base_weight=1.0,
            f1_score=0.7,
        )

        assert weight == 1.0

    def test_decay_penalty(self):
        """Test weight reduction when F1 decays"""
        normal_weight = calculate_dynamic_weight(
            base_weight=1.0,
            f1_score=0.6,
        )

        decayed_weight = calculate_dynamic_weight(
            base_weight=1.0,
            f1_score=0.15,  # Below 0.2 threshold
        )

        assert decayed_weight < normal_weight
        assert abs(decayed_weight - 0.5) < 0.01  # Penalty: 1.0 * 0.5

    def test_improvement_bonus(self):
        """Test weight increase when F1 improves"""
        # Same base weight, only F1 score differs
        baseline_weight = calculate_dynamic_weight(
            base_weight=0.8,
            f1_score=0.65,  # Below improvement threshold (0.6 + 0.1 = 0.7)
            max_weight=1.5,
        )

        improved_weight = calculate_dynamic_weight(
            base_weight=0.8,
            f1_score=0.8,  # Above improvement threshold (0.6 + 0.1 = 0.7)
            max_weight=1.5,
        )

        assert improved_weight > baseline_weight
        # Bonus: 0.8 * 1.2 = 0.96
        assert abs(improved_weight - 0.96) < 0.01

    def test_weight_bounds(self):
        """Test weight is bounded by min and max"""
        # Test max bound
        high_weight = calculate_dynamic_weight(
            base_weight=1.0,
            f1_score=0.95,
            max_weight=1.0,
        )

        assert high_weight <= 1.0

        # Test min bound
        low_weight = calculate_dynamic_weight(
            base_weight=0.5,
            f1_score=0.1,
            min_weight=0.2,
        )

        assert low_weight >= 0.2


class TestConfidenceCalculator:
    """Test ConfidenceCalculator class"""

    def test_calculator_with_default_config(self):
        """Test calculator with default config"""
        calc = ConfidenceCalculator()

        result = calc.calculate_from_freshness(
            days_since_update=5,
            has_daily_data=True,
            daily_consistent=True,
        )

        assert isinstance(result, ConfidenceBreakdown)
        assert result.total_confidence > 0

    def test_calculator_with_custom_config(self):
        """Test calculator with custom config"""
        custom_config = ConfidenceConfig(
            day_0_coefficient=0.9,
            day_7_coefficient=0.8,
            day_14_coefficient=0.7,
            day_30_coefficient=0.6,
            daily_data_bonus=0.25,
            weekly_data_bonus=0.15,
            daily_consistency_bonus=0.15,
            base_confidence=0.7,
        )

        calc = ConfidenceCalculator(config=custom_config)

        result = calc.calculate_from_freshness(
            days_since_update=1,
            has_daily_data=True,
            daily_consistent=True,
        )

        assert result.total_confidence > 0.7  # Base + bonuses

    def test_calculate_bayesian_through_calculator(self):
        """Test Bayesian calculation through calculator"""
        calc = ConfidenceCalculator()

        indicator = IndicatorPredictivePower(
            indicator_code='TEST',
            true_positive_rate=0.8,
            false_positive_rate=0.1,
            precision=0.9,
            f1_score=0.85,
            lead_time_mean=6.0,
            lead_time_std=2.0,
            lead_time_min=3.0,
            lead_time_max=12.0,
            pre_2015_correlation=0.5,
            post_2015_correlation=0.6,
            stability_score=0.8,
            current_signal='BULLISH',
            signal_strength=0.8,
            days_since_last_update=3,
            base_weight=1.0,
            current_weight=1.0,
        )

        result = calc.calculate_bayesian(
            indicators=[indicator],
            base_prior=0.5,
        )

        assert isinstance(result, RegimeProbabilities)
        assert result.confidence >= 0.5

    def test_resolve_conflict_through_calculator(self):
        """Test conflict resolution through calculator"""
        calc = ConfidenceCalculator()

        result = calc.resolve_conflict(
            daily_signal='Recovery',
            weekly_signal=None,
            monthly_signal='Recovery',
            daily_confidence=0.7,
            monthly_confidence=0.6,
            daily_duration=5,
        )

        assert isinstance(result, SignalConflict)
        assert result.final_signal == 'Recovery'
