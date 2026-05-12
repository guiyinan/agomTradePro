"""
Unit tests for Performance Analyzer components in Audit module.

Tests for:
- AttributionAnalyzer class
- IndicatorPerformanceAnalyzer class
- ThresholdValidator class
"""

from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from apps.audit.domain.entities import (
    IndicatorThresholdConfig,
    RecommendedAction,
    RegimeSnapshot,
)
from apps.audit.domain.services import (
    AttributionAnalyzer,
    IndicatorPerformanceAnalyzer,
    ThresholdValidator,
)

# ============ Fixtures ============

@pytest.fixture
def sample_threshold_config():
    """Create sample threshold configuration."""
    return IndicatorThresholdConfig(
        indicator_code="CN_PMI",
        indicator_name="PMI",
        level_low=49.0,
        level_high=51.0,
        base_weight=1.0,
        keep_min_f1=0.6,
        reduce_min_f1=0.4,
        remove_max_f1=0.3,
        decay_threshold=0.2
    )


@pytest.fixture
def sample_indicator_values():
    """Create sample indicator values."""
    base_date = date(2024, 1, 1)
    return [
        (base_date, 50.0),
        (base_date + timedelta(days=30), 51.5),
        (base_date + timedelta(days=60), 52.0),
        (base_date + timedelta(days=90), 48.5),
        (base_date + timedelta(days=120), 49.5),
        (base_date + timedelta(days=150), 51.0),
        (base_date + timedelta(days=180), 47.0),
    ]


@pytest.fixture
def sample_regime_snapshots():
    """Create sample regime snapshots."""
    base_date = date(2024, 1, 1)
    return [
        RegimeSnapshot(
            observed_at=base_date,
            dominant_regime="RECOVERY",
            confidence=0.85,
            growth_momentum_z=1.5,
            inflation_momentum_z=0.8,
            distribution={"RECOVERY": 0.70, "OVERHEAT": 0.15, "SLOWDOWN": 0.10, "STAGFLATION": 0.05}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=30),
            dominant_regime="OVERHEAT",
            confidence=0.80,
            growth_momentum_z=2.0,
            inflation_momentum_z=1.5,
            distribution={"RECOVERY": 0.20, "OVERHEAT": 0.70, "SLOWDOWN": 0.05, "STAGFLATION": 0.05}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=60),
            dominant_regime="OVERHEAT",
            confidence=0.75,
            growth_momentum_z=2.2,
            inflation_momentum_z=1.8,
            distribution={"RECOVERY": 0.15, "OVERHEAT": 0.75, "SLOWDOWN": 0.05, "STAGFLATION": 0.05}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=90),
            dominant_regime="SLOWDOWN",
            confidence=0.70,
            growth_momentum_z=-0.5,
            inflation_momentum_z=0.5,
            distribution={"RECOVERY": 0.10, "OVERHEAT": 0.10, "SLOWDOWN": 0.70, "STAGFLATION": 0.10}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=120),
            dominant_regime="RECOVERY",
            confidence=0.75,
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            distribution={"RECOVERY": 0.60, "OVERHEAT": 0.20, "SLOWDOWN": 0.15, "STAGFLATION": 0.05}
        ),
    ]


# ============ Test AttributionAnalyzer ============

class TestAttributionAnalyzer:
    """Test AttributionAnalyzer class."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer instance."""
        return AttributionAnalyzer()

    @pytest.fixture
    def sample_regime_history(self):
        """Create sample regime history."""
        return [
            {"date": date(2024, 1, 1), "regime": "RECOVERY"},
            {"date": date(2024, 2, 1), "regime": "OVERHEAT"},
            {"date": date(2024, 3, 1), "regime": "SLOWDOWN"},
        ]

    @pytest.fixture
    def sample_actual_regime_history(self):
        """Create sample actual regime history."""
        return [
            {"date": date(2024, 1, 1), "regime": "RECOVERY"},
            {"date": date(2024, 2, 1), "regime": "OVERHEAT"},
            {"date": date(2024, 3, 1), "regime": "OVERHEAT"},  # Wrong prediction
        ]

    def test_initialization_with_default_config(self):
        """Test initialization with default config."""
        analyzer = AttributionAnalyzer()
        assert analyzer.config is not None
        assert analyzer.config.risk_free_rate == 0.03

    def test_initialization_with_custom_config(self):
        """Test initialization with custom config."""
        from apps.audit.domain.entities import AttributionConfig
        custom_config = AttributionConfig(risk_free_rate=0.025)
        analyzer = AttributionAnalyzer(custom_config)
        assert analyzer.config.risk_free_rate == 0.025

    def test_analyze_regime_accuracy_empty_history(self, analyzer):
        """Test analyze_regime_accuracy with empty history."""
        result = analyzer.analyze_regime_accuracy([], [])
        assert result["total_periods"] == 0
        assert result["correct_predictions"] == 0
        assert result["accuracy"] == 0.0

    def test_analyze_regime_accuracy_all_correct(self, analyzer, sample_regime_history):
        """Test analyze_regime_accuracy with all correct predictions."""
        result = analyzer.analyze_regime_accuracy(sample_regime_history, sample_regime_history)
        assert result["total_periods"] == 3
        assert result["correct_predictions"] == 3
        assert result["accuracy"] == 1.0

    def test_analyze_regime_accuracy_mixed_predictions(
        self,
        analyzer,
        sample_regime_history,
        sample_actual_regime_history
    ):
        """Test analyze_regime_accuracy with mixed predictions."""
        result = analyzer.analyze_regime_accuracy(
            sample_regime_history,
            sample_actual_regime_history
        )
        assert result["total_periods"] == 3
        assert result["correct_predictions"] == 2
        assert abs(result["accuracy"] - 0.667) < 0.01

    def test_analyze_regime_accuracy_mismatched_lengths(self, analyzer):
        """Test analyze_regime_accuracy with mismatched list lengths."""
        predicted = [{"date": date(2024, 1, 1), "regime": "RECOVERY"}]
        actual = [
            {"date": date(2024, 1, 1), "regime": "RECOVERY"},
            {"date": date(2024, 2, 1), "regime": "OVERHEAT"},
        ]
        result = analyzer.analyze_regime_accuracy(predicted, actual)
        # Should use the minimum length
        assert result["total_periods"] == 1

    def test_build_confusion_matrix(self, analyzer):
        """Test _build_confusion_matrix method."""
        predicted = [
            {"regime": "Recovery"},
            {"regime": "Overheat"},
            {"regime": "Stagflation"},
        ]
        actual = [
            {"regime": "Recovery"},
            {"regime": "Overheat"},
            {"regime": "Recovery"},  # Wrong
        ]
        result = analyzer._build_confusion_matrix(predicted, actual)
        assert "Recovery" in result
        assert "Overheat" in result
        assert result["Recovery"]["Recovery"] == 1
        assert result["Recovery"]["Overheat"] == 0

    def test_calculate_information_ratio_empty_data(self, analyzer):
        """Test calculate_information_ratio with empty data."""
        mock_result = Mock()
        mock_result.equity_curve = []
        result = analyzer.calculate_information_ratio(mock_result, [])
        assert result is None

    def test_calculate_information_ratio_single_point(self, analyzer):
        """Test calculate_information_ratio with single equity point."""
        mock_result = Mock()
        mock_result.equity_curve = [(date(2024, 1, 1), 100000.0)]
        result = analyzer.calculate_information_ratio(mock_result, [])
        assert result is None

    def test_calculate_information_ratio_valid_data(self, analyzer):
        """Test calculate_information_ratio with valid data."""
        mock_result = Mock()
        mock_result.equity_curve = [
            (date(2024, 1, 1), 100000.0),
            (date(2024, 1, 2), 101000.0),
            (date(2024, 1, 3), 102000.0),
        ]
        benchmark_returns = [0.005, 0.005]
        result = analyzer.calculate_information_ratio(mock_result, benchmark_returns)
        assert result is not None
        assert isinstance(result, float)

    def test_calculate_information_ratio_zero_volatility(self, analyzer):
        """Test calculate_information_ratio with zero volatility."""
        mock_result = Mock()
        mock_result.equity_curve = [
            (date(2024, 1, 1), 100000.0),
            (date(2024, 1, 2), 100000.0),  # No change
            (date(2024, 1, 3), 100000.0),  # No change
        ]
        benchmark_returns = [0.0, 0.0]
        result = analyzer.calculate_information_ratio(mock_result, benchmark_returns)
        # Should return None when standard deviation is zero
        assert result is None


# ============ Test IndicatorPerformanceAnalyzer ============

class TestIndicatorPerformanceAnalyzer:
    """Test IndicatorPerformanceAnalyzer class."""

    @pytest.fixture
    def analyzer(self, sample_threshold_config):
        """Create analyzer instance."""
        return IndicatorPerformanceAnalyzer(sample_threshold_config)

    def test_initialization(self, sample_threshold_config):
        """Test initialization."""
        analyzer = IndicatorPerformanceAnalyzer(sample_threshold_config)
        assert analyzer.threshold_config == sample_threshold_config
        assert analyzer.threshold_config.indicator_code == "CN_PMI"

    def test_analyze_performance_creates_report(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test analyze_performance returns a valid report."""
        report = analyzer.analyze_performance(
            indicator_code="CN_PMI",
            indicator_values=sample_indicator_values,
            regime_history=sample_regime_snapshots,
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 6, 30)
        )
        assert report.indicator_code == "CN_PMI"
        assert report.evaluation_period_start == date(2024, 1, 1)
        assert report.evaluation_period_end == date(2024, 6, 30)

    def test_generate_signals_bullish(self, analyzer):
        """Test _generate_signals creates BULLISH signals."""
        indicator_values = [(date(2024, 1, 1), 52.0)]  # Above level_high (51)
        signals = analyzer._generate_signals(
            indicator_values,
            date(2024, 1, 1),
            date(2024, 1, 31)
        )
        assert len(signals) == 1
        assert signals[0].signal_type == "BULLISH"

    def test_generate_signals_bearish(self, analyzer):
        """Test _generate_signals creates BEARISH signals."""
        indicator_values = [(date(2024, 1, 1), 48.0)]  # Below level_low (49)
        signals = analyzer._generate_signals(
            indicator_values,
            date(2024, 1, 1),
            date(2024, 1, 31)
        )
        assert len(signals) == 1
        assert signals[0].signal_type == "BEARISH"

    def test_generate_signals_neutral(self, analyzer):
        """Test _generate_signals creates NEUTRAL signals."""
        indicator_values = [(date(2024, 1, 1), 50.0)]  # Between thresholds
        signals = analyzer._generate_signals(
            indicator_values,
            date(2024, 1, 1),
            date(2024, 1, 31)
        )
        assert len(signals) == 1
        assert signals[0].signal_type == "NEUTRAL"

    def test_generate_signals_filters_by_date_range(self, analyzer):
        """Test _generate_signals filters by date range."""
        indicator_values = [
            (date(2023, 12, 1), 52.0),  # Before range
            (date(2024, 1, 15), 51.5),  # In range
            (date(2024, 3, 1), 48.0),   # In range
        ]
        signals = analyzer._generate_signals(
            indicator_values,
            date(2024, 1, 1),
            date(2024, 2, 28)
        )
        assert len(signals) == 2

    def test_generate_signals_handles_none_values(self, analyzer):
        """Test _generate_signals handles None values."""
        indicator_values = [
            (date(2024, 1, 1), 50.0),
            (date(2024, 1, 15), None),  # Should be skipped
            (date(2024, 2, 1), 51.0),
        ]
        signals = analyzer._generate_signals(
            indicator_values,
            date(2024, 1, 1),
            date(2024, 2, 28)
        )
        assert len(signals) == 2

    def test_calculate_confusion_matrix(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test _calculate_confusion_matrix."""
        signals = analyzer._generate_signals(
            sample_indicator_values[:3],
            date(2024, 1, 1),
            date(2024, 3, 31)
        )
        regime_dict = {r.observed_at: r for r in sample_regime_snapshots}

        tp, fp, tn, fn = analyzer._calculate_confusion_matrix(
            signals,
            regime_dict,
            date(2024, 1, 1),
            date(2024, 3, 31)
        )
        # All should be non-negative integers
        assert tp >= 0
        assert fp >= 0
        assert tn >= 0
        assert fn >= 0

    def test_calculate_metrics(self, analyzer):
        """Test _calculate_metrics."""
        # Test with non-zero values
        precision, recall, f1, accuracy = analyzer._calculate_metrics(50, 10, 100, 20)
        assert 0 <= precision <= 1
        assert 0 <= recall <= 1
        assert 0 <= f1 <= 1
        assert 0 <= accuracy <= 1

    def test_calculate_metrics_zero_denominators(self, analyzer):
        """Test _calculate_metrics with edge cases."""
        # All zeros
        precision, recall, f1, accuracy = analyzer._calculate_metrics(0, 0, 0, 0)
        assert precision == 0.0
        assert recall == 0.0
        assert f1 == 0.0
        assert accuracy == 0.0

    def test_calculate_metrics_perfect_classification(self, analyzer):
        """Test _calculate_metrics with perfect classification."""
        precision, recall, f1, accuracy = analyzer._calculate_metrics(100, 0, 100, 0)
        assert precision == 1.0
        assert recall == 1.0
        assert f1 == 1.0
        assert accuracy == 1.0

    def test_calculate_lead_time(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test _calculate_lead_time."""
        signals = analyzer._generate_signals(
            sample_indicator_values,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        regime_dict = {r.observed_at: r for r in sample_regime_snapshots}

        lead_mean, lead_std = analyzer._calculate_lead_time(
            signals,
            regime_dict,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Should return valid statistics
        assert lead_mean >= 0
        assert lead_std >= 0

    def test_calculate_stability(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test _calculate_stability."""
        regime_dict = {r.observed_at: r for r in sample_regime_snapshots}

        pre_corr, post_corr, stability = analyzer._calculate_stability(
            sample_indicator_values,
            regime_dict,
            date(2020, 1, 1),  # Wide range to include pre/post 2015
            date(2024, 12, 31)
        )
        # Stability should be between 0 and 1
        assert 0 <= stability <= 1

    def test_calculate_decay_and_strength(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test _calculate_decay_and_strength."""
        signals = analyzer._generate_signals(
            sample_indicator_values,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        regime_dict = {r.observed_at: r for r in sample_regime_snapshots}

        decay, strength = analyzer._calculate_decay_and_strength(
            signals,
            regime_dict,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Both should be non-negative
        assert decay >= 0
        assert 0 <= strength <= 1

    def test_generate_recommendation_keep(self, analyzer):
        """Test _generate_recommendation returns KEEP for good performance."""
        action, weight, confidence = analyzer._generate_recommendation(
            f1_score=0.8,
            stability_score=0.75,
            decay_rate=0.1,
            signal_strength=0.7
        )
        assert action == RecommendedAction.KEEP
        assert weight == 1.0  # base_weight
        assert confidence > 0.5

    def test_generate_recommendation_increase(self, analyzer):
        """Test _generate_recommendation returns INCREASE for excellent performance."""
        action, weight, confidence = analyzer._generate_recommendation(
            f1_score=0.85,
            stability_score=0.85,
            decay_rate=0.1,
            signal_strength=0.8
        )
        assert action == RecommendedAction.INCREASE
        assert weight > 1.0  # Increased weight

    def test_generate_recommendation_decrease(self, analyzer):
        """Test _generate_recommendation returns DECREASE for mediocre performance."""
        action, weight, confidence = analyzer._generate_recommendation(
            f1_score=0.5,
            stability_score=0.5,
            decay_rate=0.15,
            signal_strength=0.5
        )
        assert action == RecommendedAction.DECREASE
        assert weight < 1.0  # Decreased weight

    def test_generate_recommendation_remove(self, analyzer):
        """Test _generate_recommendation returns REMOVE for poor performance."""
        action, weight, confidence = analyzer._generate_recommendation(
            f1_score=0.2,
            stability_score=0.2,
            decay_rate=0.5,
            signal_strength=0.3
        )
        assert action == RecommendedAction.REMOVE
        assert weight == 0.0  # min_weight

    def test_full_analysis_workflow(
        self,
        analyzer,
        sample_indicator_values,
        sample_regime_snapshots
    ):
        """Test complete analysis workflow."""
        report = analyzer.analyze_performance(
            indicator_code="CN_PMI",
            indicator_values=sample_indicator_values,
            regime_history=sample_regime_snapshots,
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 6, 30)
        )
        # Verify all fields are populated
        assert report.indicator_code == "CN_PMI"
        assert report.true_positive_count >= 0
        assert report.false_positive_count >= 0
        assert report.precision >= 0
        assert report.recall >= 0
        assert report.f1_score >= 0
        assert report.accuracy >= 0
        assert report.lead_time_mean >= 0
        assert report.lead_time_std >= 0
        assert 0 <= report.stability_score <= 1
        assert report.decay_rate >= 0
        assert 0 <= report.signal_strength <= 1


# ============ Test ThresholdValidator ============

class TestThresholdValidator:
    """Test ThresholdValidator class."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ThresholdValidator()

    @pytest.fixture
    def multiple_configs(self):
        """Create multiple threshold configurations."""
        return {
            "CN_PMI": IndicatorThresholdConfig(
                indicator_code="CN_PMI",
                indicator_name="PMI",
                level_low=49.0,
                level_high=51.0
            ),
            "CN_CPI": IndicatorThresholdConfig(
                indicator_code="CN_CPI",
                indicator_name="CPI",
                level_low=2.0,
                level_high=3.0
            ),
            "CN_GDP": IndicatorThresholdConfig(
                indicator_code="CN_GDP",
                indicator_name="GDP",
                level_low=5.5,
                level_high=6.5
            ),
        }

    @pytest.fixture
    def sample_indicators_data(self):
        """Create sample indicators data."""
        base_date = date(2024, 1, 1)
        return {
            "CN_PMI": [(base_date + timedelta(days=d), 50.0 + d * 0.1) for d in range(180)],
            "CN_CPI": [(base_date + timedelta(days=d), 2.5 + d * 0.01) for d in range(180)],
            "CN_GDP": [(base_date + timedelta(days=d*30), 6.0 + d * 0.1) for d in range(6)],
        }

    @pytest.fixture
    def sample_regime_history(self):
        """Create sample regime history."""
        base_date = date(2024, 1, 1)
        return [
            RegimeSnapshot(
                observed_at=base_date + timedelta(days=d*30),
                dominant_regime="RECOVERY" if d % 2 == 0 else "OVERHEAT",
                confidence=0.8,
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                distribution={"RECOVERY": 0.6, "OVERHEAT": 0.2, "SLOWDOWN": 0.1, "STAGFLATION": 0.1}
            )
            for d in range(6)
        ]

    def test_initialization(self, validator):
        """Test initialization."""
        assert validator.analyzers == {}

    def test_add_indicator(self, validator, multiple_configs):
        """Test adding indicator analyzers."""
        for code, config in multiple_configs.items():
            validator.add_indicator(code, config)

        assert len(validator.analyzers) == 3
        assert "CN_PMI" in validator.analyzers
        assert "CN_CPI" in validator.analyzers
        assert "CN_GDP" in validator.analyzers

    def test_validate_all_empty(self, validator):
        """Test validate_all with no analyzers."""
        reports = validator.validate_all({}, [], date(2024, 1, 1), date(2024, 12, 31))
        assert reports == []

    def test_validate_all_with_data(
        self,
        validator,
        multiple_configs,
        sample_indicators_data,
        sample_regime_history
    ):
        """Test validate_all with sample data."""
        # Add analyzers
        for code, config in multiple_configs.items():
            validator.add_indicator(code, config)

        reports = validator.validate_all(
            sample_indicators_data,
            sample_regime_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Should return reports for all indicators
        assert len(reports) == 3
        # Each report should have valid indicator_code
        for report in reports:
            assert report.indicator_code in multiple_configs

    def test_validate_all_missing_indicator_data(
        self,
        validator,
        multiple_configs,
        sample_regime_history
    ):
        """Test validate_all handles missing indicator data."""
        # Add analyzers
        for code, config in multiple_configs.items():
            validator.add_indicator(code, config)

        # Only provide data for one indicator
        incomplete_data = {
            "CN_PMI": [(date(2024, 1, 1), 50.0)]
        }

        reports = validator.validate_all(
            incomplete_data,
            sample_regime_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Should only return report for CN_PMI
        assert len(reports) == 1
        assert reports[0].indicator_code == "CN_PMI"

    def test_analyzer_type_after_add(self, validator, multiple_configs):
        """Test that added analyzers are correct type."""
        validator.add_indicator("CN_PMI", multiple_configs["CN_PMI"])
        assert isinstance(validator.analyzers["CN_PMI"], IndicatorPerformanceAnalyzer)


# ============ Test Edge Cases and Integration ============

class TestEdgeCases:
    """Test edge cases and integration scenarios."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer with standard config."""
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test Indicator",
            level_low=0.0,
            level_high=100.0
        )
        return IndicatorPerformanceAnalyzer(config)

    def test_analyze_performance_with_empty_data(self, analyzer):
        """Test analyze_performance with minimal data."""
        report = analyzer.analyze_performance(
            indicator_code="TEST",
            indicator_values=[],
            regime_history=[],
            evaluation_start=date(2024, 1, 1),
            evaluation_end=date(2024, 12, 31)
        )
        # Should still return a valid report structure
        assert report.indicator_code == "TEST"
        assert report.true_positive_count == 0
        assert report.false_positive_count == 0

    def test_confidence_calculation_extreme_values(self, analyzer):
        """Test confidence calculation with extreme indicator values."""
        # Very high value (far above threshold)
        signals = analyzer._generate_signals(
            [(date(2024, 1, 1), 1000.0)],
            date(2024, 1, 1),
            date(2024, 1, 31)
        )
        # Confidence should be capped at 1.0
        assert signals[0].confidence <= 1.0

    def test_single_regime_snapshot(self, analyzer):
        """Test with single regime snapshot (no regime changes)."""
        regime = RegimeSnapshot(
            observed_at=date(2024, 1, 1),
            dominant_regime="RECOVERY",
            confidence=0.8,
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            distribution={"RECOVERY": 1.0}
        )
        lead_mean, lead_std = analyzer._calculate_lead_time(
            [],
            {regime.observed_at: regime},
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Should handle gracefully
        assert lead_mean >= 0
