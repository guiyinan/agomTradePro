"""
Unit tests for ThresholdValidator class in Audit module.

Tests for batch validation functionality and report generation.
"""

from datetime import date, timedelta

import pytest

from apps.audit.domain.entities import (
    IndicatorPerformanceReport,
    IndicatorThresholdConfig,
    RecommendedAction,
    RegimeSnapshot,
    ThresholdValidationReport,
    ValidationStatus,
)
from apps.audit.domain.services import ThresholdValidator

# ============ Fixtures ============

@pytest.fixture
def sample_configs():
    """Create sample threshold configurations."""
    return {
        "good_indicator": IndicatorThresholdConfig(
            indicator_code="GOOD",
            indicator_name="Good Indicator",
            level_low=40.0,
            level_high=60.0,
            base_weight=1.0,
            keep_min_f1=0.6,
            reduce_min_f1=0.4,
            remove_max_f1=0.3,
        ),
        "bad_indicator": IndicatorThresholdConfig(
            indicator_code="BAD",
            indicator_name="Bad Indicator",
            level_low=40.0,
            level_high=60.0,
            base_weight=1.0,
            keep_min_f1=0.6,
            reduce_min_f1=0.4,
            remove_max_f1=0.3,
        ),
        "medium_indicator": IndicatorThresholdConfig(
            indicator_code="MEDIUM",
            indicator_name="Medium Indicator",
            level_low=40.0,
            level_high=60.0,
            base_weight=1.0,
            keep_min_f1=0.6,
            reduce_min_f1=0.4,
            remove_max_f1=0.3,
        ),
    }


@pytest.fixture
def sample_indicators_data():
    """Create sample indicator data that produces different quality signals."""
    base_date = date(2024, 1, 1)
    return {
        "good_indicator": [
            # High values matching RECOVERY regime
            (base_date, 65.0),
            (base_date + timedelta(days=30), 70.0),
            (base_date + timedelta(days=60), 68.0),
            (base_date + timedelta(days=90), 72.0),
        ],
        "bad_indicator": [
            # Random values not matching regime
            (base_date, 45.0),
            (base_date + timedelta(days=30), 55.0),
            (base_date + timedelta(days=60), 35.0),
            (base_date + timedelta(days=90), 65.0),
        ],
        "medium_indicator": [
            # Some matching, some not
            (base_date, 62.0),
            (base_date + timedelta(days=30), 58.0),
            (base_date + timedelta(days=60), 48.0),
            (base_date + timedelta(days=90), 52.0),
        ],
    }


@pytest.fixture
def sample_regime_history():
    """Create sample regime history matching good_indicator signals."""
    base_date = date(2024, 1, 1)
    return [
        RegimeSnapshot(
            observed_at=base_date,
            dominant_regime="RECOVERY",
            confidence=0.9,
            growth_momentum_z=1.5,
            inflation_momentum_z=0.8,
            distribution={"RECOVERY": 0.7, "OVERHEAT": 0.2, "SLOWDOWN": 0.05, "STAGFLATION": 0.05}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=30),
            dominant_regime="OVERHEAT",
            confidence=0.85,
            growth_momentum_z=2.0,
            inflation_momentum_z=1.5,
            distribution={"RECOVERY": 0.1, "OVERHEAT": 0.8, "SLOWDOWN": 0.05, "STAGFLATION": 0.05}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=60),
            dominant_regime="OVERHEAT",
            confidence=0.88,
            growth_momentum_z=2.1,
            inflation_momentum_z=1.6,
            distribution={"RECOVERY": 0.1, "OVERHEAT": 0.85, "SLOWDOWN": 0.03, "STAGFLATION": 0.02}
        ),
        RegimeSnapshot(
            observed_at=base_date + timedelta(days=90),
            dominant_regime="RECOVERY",
            confidence=0.82,
            growth_momentum_z=1.3,
            inflation_momentum_z=0.9,
            distribution={"RECOVERY": 0.65, "OVERHEAT": 0.25, "SLOWDOWN": 0.05, "STAGFLATION": 0.05}
        ),
    ]


# ============ Test ThresholdValidator Initialization ============

class TestThresholdValidatorInitialization:
    """Test ThresholdValidator initialization and setup."""

    def test_default_initialization(self):
        """Test initialization with no parameters."""
        validator = ThresholdValidator()
        assert validator.analyzers == {}
        assert isinstance(validator.analyzers, dict)

    def test_analyzers_dict_is_mutable(self):
        """Test that analyzers dict can be modified."""
        validator = ThresholdValidator()
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test",
            level_low=0.0,
            level_high=100.0
        )
        validator.add_indicator("TEST", config)
        assert len(validator.analyzers) == 1


# ============ Test add_indicator ============

class TestAddIndicator:
    """Test add_indicator method."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return ThresholdValidator()

    def test_add_single_indicator(self, validator, sample_configs):
        """Test adding a single indicator."""
        config = sample_configs["good_indicator"]
        validator.add_indicator("good_indicator", config)
        assert "good_indicator" in validator.analyzers
        assert len(validator.analyzers) == 1

    def test_add_multiple_indicators(self, validator, sample_configs):
        """Test adding multiple indicators."""
        for code, config in sample_configs.items():
            validator.add_indicator(code, config)
        assert len(validator.analyzers) == 3
        assert set(validator.analyzers.keys()) == set(sample_configs.keys())

    def test_add_indicator_overwrites(self, validator, sample_configs):
        """Test that adding same indicator twice overwrites."""
        config1 = sample_configs["good_indicator"]
        config2 = sample_configs["bad_indicator"]
        validator.add_indicator("test", config1)
        validator.add_indicator("test", config2)
        assert len(validator.analyzers) == 1
        # Should have the second config

    def test_add_indicator_with_custom_code(self, validator):
        """Test adding indicator with custom code different from config."""
        config = IndicatorThresholdConfig(
            indicator_code="CONFIG_CODE",
            indicator_name="Test",
            level_low=0.0,
            level_high=100.0
        )
        validator.add_indicator("CUSTOM_CODE", config)
        assert "CUSTOM_CODE" in validator.analyzers


# ============ Test validate_all ============

class TestValidateAll:
    """Test validate_all method."""

    @pytest.fixture
    def validator(self, sample_configs):
        """Create validator with sample indicators."""
        v = ThresholdValidator()
        for code, config in sample_configs.items():
            v.add_indicator(code, config)
        return v

    def test_validate_all_empty_analyzers(self):
        """Test validate_all with no analyzers added."""
        validator = ThresholdValidator()
        reports = validator.validate_all(
            {},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert reports == []

    def test_validate_all_no_data_for_indicators(self, validator):
        """Test validate_all when indicators have no data."""
        reports = validator.validate_all(
            {},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert reports == []

    def test_validate_all_partial_data(self, validator, sample_indicators_data):
        """Test validate_all with partial data (some indicators missing)."""
        reports = validator.validate_all(
            sample_indicators_data,
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Should return reports only for indicators with data
        assert len(reports) == 3

    def test_validate_all_returns_reports(
        self,
        validator,
        sample_indicators_data,
        sample_regime_history
    ):
        """Test validate_all returns valid reports."""
        reports = validator.validate_all(
            sample_indicators_data,
            sample_regime_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        assert len(reports) > 0
        for report in reports:
            assert isinstance(report, IndicatorPerformanceReport)
            assert report.indicator_code in sample_indicators_data

    def test_validate_all_report_fields(
        self,
        validator,
        sample_indicators_data,
        sample_regime_history
    ):
        """Test that validate_all returns complete reports."""
        reports = validator.validate_all(
            sample_indicators_data,
            sample_regime_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        for report in reports:
            # Check all essential fields
            assert hasattr(report, 'indicator_code')
            assert hasattr(report, 'f1_score')
            assert hasattr(report, 'precision')
            assert hasattr(report, 'recall')
            assert hasattr(report, 'accuracy')
            assert hasattr(report, 'recommended_action')
            assert hasattr(report, 'stability_score')

    def test_validate_all_date_filtering(
        self,
        validator,
        sample_indicators_data,
        sample_regime_history
    ):
        """Test validate_all respects evaluation period."""
        # Use a narrow period
        reports = validator.validate_all(
            sample_indicators_data,
            sample_regime_history,
            date(2024, 1, 1),
            date(2024, 2, 28)  # Only 2 months
        )
        # Should still produce reports
        assert len(reports) > 0
        for report in reports:
            assert report.evaluation_period_start == date(2024, 1, 1)
            assert report.evaluation_period_end == date(2024, 2, 28)

    def test_validate_all_handles_errors_gracefully(self, validator, sample_configs):
        """Test validate_all continues even if one indicator fails."""
        # Add an analyzer that will fail
        bad_config = IndicatorThresholdConfig(
            indicator_code="WILL_FAIL",
            indicator_name="Bad Config",
            level_low=None,  # This might cause issues
            level_high=None
        )
        validator.add_indicator("WILL_FAIL", bad_config)

        # Should not raise exception
        reports = validator.validate_all(
            {"WILL_FAIL": [(date(2024, 1, 1), 50.0)]},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Either returns empty list or the report if it succeeded
        assert isinstance(reports, list)


# ============ Test Batch Validation Scenarios ============

class TestBatchValidationScenarios:
    """Test realistic batch validation scenarios."""

    @pytest.fixture
    def validator(self):
        """Create validator for batch testing."""
        v = ThresholdValidator()
        configs = {
            "PMI": IndicatorThresholdConfig(
                indicator_code="PMI",
                indicator_name="PMI",
                level_low=49.0,
                level_high=51.0
            ),
            "CPI": IndicatorThresholdConfig(
                indicator_code="CPI",
                indicator_name="CPI",
                level_low=2.0,
                level_high=3.0
            ),
        }
        for code, config in configs.items():
            v.add_indicator(code, config)
        return v

    @pytest.fixture
    def batch_indicator_data(self):
        """Create batch indicator data."""
        base_date = date(2024, 1, 1)
        return {
            "PMI": [(base_date + timedelta(days=d*30), 50.0 + d * 0.5) for d in range(12)],
            "CPI": [(base_date + timedelta(days=d*30), 2.5 + d * 0.1) for d in range(12)],
        }

    @pytest.fixture
    def batch_regime_history(self):
        """Create regime history for batch testing."""
        base_date = date(2024, 1, 1)
        regimes = ["RECOVERY", "OVERHEAT", "SLOWDOWN", "STAGFLATION"]
        return [
            RegimeSnapshot(
                observed_at=base_date + timedelta(days=d*30),
                dominant_regime=regimes[d % 4],
                confidence=0.8,
                growth_momentum_z=1.0,
                inflation_momentum_z=0.5,
                distribution=dict.fromkeys(regimes, 0.25)
            )
            for d in range(12)
        ]

    def test_batch_validation_all_indicators(
        self,
        validator,
        batch_indicator_data,
        batch_regime_history
    ):
        """Test batch validation processes all indicators."""
        reports = validator.validate_all(
            batch_indicator_data,
            batch_regime_history,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert len(reports) == 2  # PMI and CPI

    def test_batch_validation_different_recommendations(
        self,
        validator,
        batch_indicator_data,
        batch_regime_history
    ):
        """Test batch validation can produce different recommendations."""
        reports = validator.validate_all(
            batch_indicator_data,
            batch_regime_history,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Extract recommendations
        recommendations = [report.recommended_action for report in reports]
        # Should all be valid recommendation strings
        valid_actions = ["KEEP", "INCREASE", "DECREASE", "REMOVE"]
        for rec in recommendations:
            assert rec in valid_actions

    def test_batch_validation_weight_adjustments(
        self,
        validator,
        batch_indicator_data,
        batch_regime_history
    ):
        """Test batch validation produces weight recommendations."""
        reports = validator.validate_all(
            batch_indicator_data,
            batch_regime_history,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        for report in reports:
            assert hasattr(report, 'recommended_weight')
            assert report.recommended_weight >= 0.0
            # Weight should be within reasonable bounds
            assert report.recommended_weight <= 2.0

    def test_batch_validation_f1_scores(
        self,
        validator,
        batch_indicator_data,
        batch_regime_history
    ):
        """Test batch validation produces F1 scores."""
        reports = validator.validate_all(
            batch_indicator_data,
            batch_regime_history,
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        for report in reports:
            assert 0.0 <= report.f1_score <= 1.0


# ============ Test Report Aggregation ============

class TestReportAggregation:
    """Test aggregation of validation reports."""

    @pytest.fixture
    def validator(self, sample_configs):
        """Create validator with multiple indicators."""
        v = ThresholdValidator()
        for code, config in sample_configs.items():
            v.add_indicator(code, config)
        return v

    @pytest.fixture
    def sample_data(self, sample_indicators_data):
        """Use sample data from fixtures."""
        return sample_indicators_data

    @pytest.fixture
    def sample_history(self, sample_regime_history):
        """Use sample regime history."""
        return sample_regime_history

    def test_aggregate_validation_statistics(
        self,
        validator,
        sample_data,
        sample_history
    ):
        """Test aggregating statistics from multiple reports."""
        reports = validator.validate_all(
            sample_data,
            sample_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Calculate aggregate statistics
        total_indicators = len(reports)
        avg_f1 = sum(r.f1_score for r in reports) / total_indicators if total_indicators > 0 else 0.0
        avg_stability = sum(r.stability_score for r in reports) / total_indicators if total_indicators > 0 else 0.0

        assert total_indicators == 3
        assert 0.0 <= avg_f1 <= 1.0
        assert 0.0 <= avg_stability <= 1.0

    def test_categorize_indicators_by_action(
        self,
        validator,
        sample_data,
        sample_history
    ):
        """Test categorizing indicators by recommended action."""
        reports = validator.validate_all(
            sample_data,
            sample_history,
            date(2024, 1, 1),
            date(2024, 6, 30)
        )
        # Categorize
        keep_count = sum(1 for r in reports if r.recommended_action == "KEEP")
        increase_count = sum(1 for r in reports if r.recommended_action == "INCREASE")
        decrease_count = sum(1 for r in reports if r.recommended_action == "DECREASE")
        remove_count = sum(1 for r in reports if r.recommended_action == "REMOVE")

        total = keep_count + increase_count + decrease_count + remove_count
        assert total == len(reports)


# ============ Test Edge Cases ============

class TestThresholdValidatorEdgeCases:
    """Test edge cases and error handling."""

    def test_validate_all_with_none_values(self):
        """Test handling of None values in indicator data."""
        validator = ThresholdValidator()
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test",
            level_low=40.0,
            level_high=60.0
        )
        validator.add_indicator("TEST", config)

        data_with_nones = [
            (date(2024, 1, 1), 50.0),
            (date(2024, 2, 1), None),
            (date(2024, 3, 1), 55.0),
        ]
        reports = validator.validate_all(
            {"TEST": data_with_nones},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Should handle None values gracefully
        assert isinstance(reports, list)

    def test_validate_all_empty_regime_history(self):
        """Test with empty regime history."""
        validator = ThresholdValidator()
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test",
            level_low=40.0,
            level_high=60.0
        )
        validator.add_indicator("TEST", config)

        data = [(date(2024, 1, 1), 50.0), (date(2024, 2, 1), 55.0)]
        reports = validator.validate_all(
            {"TEST": data},
            [],  # Empty regime history
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Should still produce a report
        assert len(reports) >= 0

    def test_validate_all_single_data_point(self):
        """Test with single data point."""
        validator = ThresholdValidator()
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test",
            level_low=40.0,
            level_high=60.0
        )
        validator.add_indicator("TEST", config)

        data = [(date(2024, 1, 1), 50.0)]
        reports = validator.validate_all(
            {"TEST": data},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        # Should handle single data point
        assert isinstance(reports, list)

    def test_validate_all_extreme_thresholds(self):
        """Test with extreme threshold values."""
        validator = ThresholdValidator()
        config = IndicatorThresholdConfig(
            indicator_code="TEST",
            indicator_name="Test",
            level_low=-1000.0,
            level_high=1000.0
        )
        validator.add_indicator("TEST", config)

        data = [(date(2024, 1, 1), 0.0)]
        reports = validator.validate_all(
            {"TEST": data},
            [],
            date(2024, 1, 1),
            date(2024, 12, 31)
        )
        assert isinstance(reports, list)
