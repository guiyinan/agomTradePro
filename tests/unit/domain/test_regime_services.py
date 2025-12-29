"""
Unit tests for Regime Domain Services.

Pure Domain layer tests using only Python standard library.
"""

import pytest
from datetime import date
from apps.regime.domain.services import (
    sigmoid,
    calculate_regime_distribution,
    calculate_momentum,
    calculate_rolling_zscore,
    find_dominant_regime,
    RegimeCalculator,
    RegimeCalculationResult,
)


class TestSigmoid:
    """Tests for sigmoid function"""

    def test_sigmoid_zero(self):
        """Test sigmoid(0) = 0.5"""
        result = sigmoid(0.0)
        assert result == pytest.approx(0.5)

    def test_sigmoid_positive(self):
        """Test sigmoid with positive input"""
        result = sigmoid(1.0, k=2.0)
        assert result > 0.5
        assert result < 1.0

    def test_sigmoid_negative(self):
        """Test sigmoid with negative input"""
        result = sigmoid(-1.0, k=2.0)
        assert result < 0.5
        assert result > 0.0

    def test_sigmoid_large_positive(self):
        """Test sigmoid with large positive input (overflow protection)"""
        result = sigmoid(100.0)
        assert result == pytest.approx(1.0)

    def test_sigmoid_large_negative(self):
        """Test sigmoid with large negative input (overflow protection)"""
        result = sigmoid(-100.0)
        assert result == pytest.approx(0.0)

    def test_sigmoid_custom_k(self):
        """Test sigmoid with custom slope parameter"""
        result_steep = sigmoid(1.0, k=10.0)
        result_shallow = sigmoid(1.0, k=0.5)
        assert result_steep > result_shallow


class TestRegimeDistribution:
    """Tests for calculate_regime_distribution"""

    def test_distribution_sum_to_one(self):
        """Test that probabilities sum to 1"""
        result = calculate_regime_distribution(0.0, 0.0)
        total = sum(result.values())
        assert total == pytest.approx(1.0)

    def test_distribution_positive_z(self):
        """Test with positive z-scores (both up)"""
        result = calculate_regime_distribution(2.0, 2.0)
        # Both positive -> Overheat should be dominant
        assert result["Overheat"] > 0.4
        assert result["Deflation"] < 0.1

    def test_distribution_negative_z(self):
        """Test with negative z-scores (both down)"""
        result = calculate_regime_distribution(-2.0, -2.0)
        # Both negative -> Deflation should be dominant
        assert result["Deflation"] > 0.4
        assert result["Overheat"] < 0.1

    def test_distribution_recovery(self):
        """Test Recovery regime (growth up, inflation down)"""
        result = calculate_regime_distribution(2.0, -2.0)
        # Growth up, inflation down -> Recovery
        assert result["Recovery"] > 0.4

    def test_distribution_stagflation(self):
        """Test Stagflation regime (growth down, inflation up)"""
        result = calculate_regime_distribution(-2.0, 2.0)
        # Growth down, inflation up -> Stagflation
        assert result["Stagflation"] > 0.4

    def test_distribution_neutral(self):
        """Test with neutral z-scores near zero"""
        result = calculate_regime_distribution(0.0, 0.0)
        # All should be similar near 0.25
        for regime in result.values():
            assert 0.2 < regime < 0.3


class TestMomentum:
    """Tests for calculate_momentum"""

    def test_momentum_basic(self):
        """Test basic momentum calculation"""
        series = [100.0, 102.0, 105.0, 110.0]
        result = calculate_momentum(series, period=2)
        # First 2 values should be 0.0
        assert result[0] == 0.0
        assert result[1] == 0.0
        # Third value: (105 - 100) / 100 = 0.05
        assert result[2] == pytest.approx(0.05)
        # Fourth value: (110 - 102) / 102 ≈ 0.078
        assert result[3] == pytest.approx(0.078, rel=0.01)

    def test_momentum_zero_past_value(self):
        """Test momentum when past value is zero"""
        series = [0.0, 1.0, 2.0, 3.0]
        result = calculate_momentum(series, period=2)
        # Should return 0.0 for division by zero case
        assert result[2] == 0.0

    def test_momentum_series_shorter_than_period(self):
        """Test with series shorter than period"""
        series = [1.0, 2.0]
        result = calculate_momentum(series, period=5)
        assert len(result) == 2
        assert all(v == 0.0 for v in result)

    def test_momentum_declining_series(self):
        """Test with declining series"""
        series = [100.0, 95.0, 90.0, 85.0]
        result = calculate_momentum(series, period=2)
        # Should be negative
        assert result[2] < 0
        assert result[3] < 0


class TestRollingZScore:
    """Tests for calculate_rolling_zscore"""

    def test_zscore_basic(self):
        """Test basic z-score calculation"""
        series = [100.0] * 30
        result = calculate_rolling_zscore(series, window=10, min_periods=5)
        # Constant series should have z-scores near 0
        assert result[-1] == pytest.approx(0.0, abs=0.01)

    def test_zscore_min_periods(self):
        """Test min_periods parameter"""
        series = [1.0, 2.0, 3.0]
        result = calculate_rolling_zscore(series, window=10, min_periods=3)
        # First 2 values should be 0.0
        assert result[0] == 0.0
        assert result[1] == 0.0
        # Third value should have a valid z-score
        assert result[2] != 0.0

    def test_zscore_increasing_series(self):
        """Test with increasing series"""
        series = list(range(1, 31))  # 1 to 30
        result = calculate_rolling_zscore(series, window=10, min_periods=5)
        # Later values should have positive z-scores
        assert result[-1] > 0

    def test_zscore_empty_series(self):
        """Test with empty series"""
        result = calculate_rolling_zscore([], window=10, min_periods=5)
        assert result == []


class TestFindDominantRegime:
    """Tests for find_dominant_regime"""

    def test_find_dominant_clear_winner(self):
        """Test with clear dominant regime"""
        distribution = {
            "Recovery": 0.6,
            "Overheat": 0.2,
            "Stagflation": 0.1,
            "Deflation": 0.1,
        }
        regime, confidence = find_dominant_regime(distribution)
        assert regime == "Recovery"
        assert confidence == 0.6

    def test_find_dominant_tie(self):
        """Test with tie (first one wins)"""
        distribution = {
            "Recovery": 0.3,
            "Overheat": 0.3,
            "Stagflation": 0.2,
            "Deflation": 0.2,
        }
        regime, confidence = find_dominant_regime(distribution)
        assert confidence == 0.3
        # Recovery is first in dict order (Python 3.7+ preserves insertion)


class TestRegimeCalculator:
    """Tests for RegimeCalculator"""

    @pytest.fixture
    def calculator(self):
        """Create a RegimeCalculator instance"""
        return RegimeCalculator(
            momentum_period=3,
            zscore_window=60,
            zscore_min_periods=24,
            sigmoid_k=2.0
        )

    def test_calculate_insufficient_data(self, calculator):
        """Test with insufficient data"""
        growth_series = [50.0, 51.0]
        inflation_series = [2.0, 2.1]
        result = calculator.calculate(growth_series, inflation_series, date(2024, 1, 1))

        assert isinstance(result, RegimeCalculationResult)
        assert len(result.warnings) > 0
        assert "数据不足" in result.warnings[0]

    def test_calculate_mismatched_length(self, calculator):
        """Test with mismatched series lengths"""
        growth_series = [50.0] * 30
        inflation_series = [2.0] * 25
        result = calculator.calculate(growth_series, inflation_series, date(2024, 1, 1))

        assert isinstance(result, RegimeCalculationResult)
        assert len(result.warnings) > 0
        assert "长度不一致" in result.warnings[0]

    def test_calculate_valid_data(self, calculator):
        """Test with valid data"""
        # Create synthetic data: 30 months of growth and inflation
        growth_series = [50.0 + i * 0.1 for i in range(30)]  # Gradually increasing
        inflation_series = [2.0 + i * 0.01 for i in range(30)]  # Gradually increasing

        result = calculator.calculate(growth_series, inflation_series, date(2024, 1, 1))

        assert isinstance(result, RegimeCalculationResult)
        assert result.snapshot.observed_at == date(2024, 1, 1)
        assert result.snapshot.dominant_regime in [
            "Recovery", "Overheat", "Stagflation", "Deflation"
        ]
        # Distribution should sum to 1
        assert sum(result.snapshot.distribution.values()) == pytest.approx(1.0)

    def test_calculate_at_point(self, calculator):
        """Test calculate_at_point for backtesting"""
        growth_history = [50.0 + i * 0.1 for i in range(25)]
        inflation_history = [2.0 + i * 0.01 for i in range(25)]

        result = calculator.calculate_at_point(
            growth_value=52.6,
            inflation_value=2.26,
            growth_history=growth_history,
            inflation_history=inflation_history,
            as_of_date=date(2024, 1, 1)
        )

        assert isinstance(result, RegimeCalculationResult)
        # Should have 26 values in calculation (25 history + 1 current)
        assert result.snapshot.growth_momentum_z is not None

    def test_calculator_custom_params(self):
        """Test calculator with custom parameters"""
        calculator = RegimeCalculator(
            momentum_period=6,
            zscore_window=120,
            zscore_min_periods=48,
            sigmoid_k=3.0
        )
        assert calculator.momentum_period == 6
        assert calculator.zscore_window == 120
        assert calculator.zscore_min_periods == 48
        assert calculator.sigmoid_k == 3.0


class TestRegimeSnapshot:
    """Tests for RegimeSnapshot entity"""

    def test_is_high_confidence(self):
        """Test is_high_confidence method"""
        from apps.regime.domain.entities import RegimeSnapshot

        snapshot_high = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            distribution={"Recovery": 0.5, "Overheat": 0.3, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.5,
            observed_at=date(2024, 1, 1)
        )

        snapshot_low = RegimeSnapshot(
            growth_momentum_z=0.1,
            inflation_momentum_z=0.1,
            distribution={"Recovery": 0.28, "Overheat": 0.25, "Stagflation": 0.24, "Deflation": 0.23},
            dominant_regime="Recovery",
            confidence=0.28,
            observed_at=date(2024, 1, 1)
        )

        assert snapshot_high.is_high_confidence(threshold=0.3) is True
        assert snapshot_low.is_high_confidence(threshold=0.3) is False

    def test_snapshot_frozen(self):
        """Test that RegimeSnapshot is frozen"""
        from apps.regime.domain.entities import RegimeSnapshot

        snapshot = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            distribution={"Recovery": 0.5, "Overheat": 0.3, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.5,
            observed_at=date(2024, 1, 1)
        )

        # Frozen dataclass should raise FrozenInstanceError on modification
        with pytest.raises(Exception):  # FrozenInstanceError
            snapshot.growth_momentum_z = 2.0
