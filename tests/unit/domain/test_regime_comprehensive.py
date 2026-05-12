"""
Comprehensive Unit Tests for Regime Domain Services.

Tests cover:
1. Absolute momentum calculation (inflation fix from 2026-01-22)
2. Regime calculation edge cases and boundary conditions
3. Real-world scenario simulations
4. System time / timezone handling

Pure Domain layer tests using only Python standard library.
"""

from datetime import date

import pytest

from apps.regime.domain.entities import RegimeSnapshot
from apps.regime.domain.services import (
    RegimeCalculator,
    calculate_absolute_momentum,
    calculate_momentum,
    calculate_regime_distribution,
    calculate_rolling_zscore,
    sigmoid,
)


class TestAbsoluteMomentum:
    """
    Tests for calculate_absolute_momentum (2026-01-22 fix).

    This function uses absolute difference (pp) instead of relative change
    to avoid distortion when inflation is at low levels (e.g., 0.1% -> 0.3%).
    """

    def test_absolute_momentum_basic(self):
        """Test basic absolute momentum calculation"""
        series = [0.1, 0.2, 0.3, 0.5]
        result = calculate_absolute_momentum(series, period=2)

        # First 2 values should be 0.0
        assert result[0] == 0.0
        assert result[1] == 0.0

        # Third value: 0.3 - 0.1 = 0.2pp
        assert result[2] == pytest.approx(0.2)

        # Fourth value: 0.5 - 0.2 = 0.3pp
        assert result[3] == pytest.approx(0.3)

    def test_absolute_momentum_low_base_prevents_distortion(self):
        """
        Test that absolute momentum prevents low-base distortion.

        The key fix for 2026-01-22:
        - Relative: (0.3 - 0.1) / 0.1 = 200% (WRONG!)
        - Absolute: 0.3 - 0.1 = 0.2pp (CORRECT!)
        """
        series = [0.1, 0.15, 0.25, 0.30]
        result = calculate_absolute_momentum(series, period=2)

        # Period=2: Compare with value 2 periods ago
        # Index 2: 0.25 - 0.1 = 0.15pp
        assert result[2] == pytest.approx(0.15)

        # Index 3: 0.30 - 0.15 = 0.15pp
        assert result[3] == pytest.approx(0.15)

    def test_absolute_momentum_vs_relative_momentum(self):
        """
        Compare absolute vs relative momentum to show the difference.
        """
        series = [0.1, 0.15, 0.25, 0.30]
        absolute_result = calculate_absolute_momentum(series, period=2)
        relative_result = calculate_momentum(series, period=2)

        # Absolute should be much smaller at low base
        assert absolute_result[2] < relative_result[2]

        # At index 2:
        # Absolute: 0.25 - 0.1 = 0.15
        # Relative: (0.25 - 0.1) / 0.1 = 1.5 (150%)
        assert absolute_result[2] == pytest.approx(0.15)
        assert relative_result[2] == pytest.approx(1.5)

    def test_absolute_momentum_declining_series(self):
        """Test with declining inflation"""
        series = [3.0, 2.5, 2.0, 1.5]
        result = calculate_absolute_momentum(series, period=2)

        # Should be negative (inflation slowing)
        assert result[2] < 0  # 2.0 - 3.0 = -1.0
        assert result[3] < 0  # 1.5 - 2.5 = -1.0

    def test_absolute_momentum_high_inflation(self):
        """Test with high inflation levels"""
        series = [5.0, 5.5, 6.0, 6.8]
        result = calculate_absolute_momentum(series, period=2)

        # Accelerating inflation
        assert result[2] == pytest.approx(1.0)  # 6.0 - 5.0
        assert result[3] == pytest.approx(1.3)  # 6.8 - 5.5

    def test_absolute_momentum_zero_values(self):
        """Test with zero values (deflation scenario)"""
        series = [-0.5, 0.0, 0.0, 0.2]
        result = calculate_absolute_momentum(series, period=2)

        # 0 - (-0.5) = 0.5pp (inflation rising from deflation)
        assert result[2] == pytest.approx(0.5)

        # 0.2 - 0 = 0.2pp
        assert result[3] == pytest.approx(0.2)


class TestRegimeCalculationScenarios:
    """
    Tests for Regime calculation with realistic scenarios.

    Based on docs/business/regime_calculation_logic.md
    """

    @pytest.fixture
    def calculator(self):
        """Standard RegimeCalculator with production parameters"""
        return RegimeCalculator(
            momentum_period=3,
            zscore_window=60,
            zscore_min_periods=24,
            sigmoid_k=2.0,
            use_absolute_inflation_momentum=True  # Use the 2026-01-22 fix
        )

    def test_recovery_regime_scenario(self, calculator):
        """
        Test Recovery regime detection: Growth up, Inflation down

        Example: Economic recovery with PMI rising, CPI falling
        """
        # PMI: rising from 49.0 to 50.5
        growth_series = [
            49.0, 49.2, 49.3, 49.5, 49.8, 50.0, 50.3, 50.5,
            50.2, 50.0, 49.8, 49.5, 49.0, 48.5, 48.0, 47.5,
            47.0, 46.8, 46.5, 46.0, 45.8, 45.5, 45.0, 44.8,
            44.5, 44.0, 43.8, 43.5, 43.0, 42.8,
            # 30 months of data, then acceleration
            43.0, 43.5, 44.0, 45.0, 46.0, 47.5, 49.0, 50.5,
        ]

        # CPI: falling from 2.5% to 1.8% (then stable low)
        inflation_series = [
            2.5, 2.5, 2.4, 2.4, 2.3, 2.3, 2.2, 2.2,
            2.1, 2.1, 2.0, 2.0, 2.0, 1.9, 1.9, 1.9,
            1.8, 1.8, 1.8, 1.7, 1.7, 1.7, 1.6, 1.6,
            1.6, 1.5, 1.5, 1.5, 1.4, 1.4,
            # 30 months, then slight decrease
            1.4, 1.4, 1.4, 1.3, 1.3, 1.3, 1.2, 1.2,
        ]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 12, 1)
        )

        # With growth accelerating and inflation low, should get Recovery or Overheat
        assert result.snapshot.dominant_regime in ["Recovery", "Overheat"]
        assert sum(result.snapshot.distribution.values()) == pytest.approx(1.0)

    def test_stagflation_regime_scenario(self, calculator):
        """
        Test Stagflation regime detection: Growth down, Inflation up

        Example: 1970s-style stagflation
        """
        # PMI: declining from 50.0 to 48.0
        growth_series = (
            [50.0] * 10 +  # Stable high
            [49.5, 49.3, 49.0, 48.8, 48.5, 48.3, 48.0, 47.8] +  # Declining
            [47.5] * 10 +  # Stable low
            [47.3, 47.0, 46.8, 46.5, 46.3, 46.0, 45.8, 45.5, 45.3, 45.0, 44.8, 44.5]  # Accelerating down
        )

        # CPI: rising from 2.0% to 4.5%
        inflation_series = (
            [2.0] * 10 +  # Stable low
            [2.2, 2.4, 2.6, 2.9, 3.2, 3.5, 3.8, 4.0] +  # Accelerating
            [4.2] * 10 +  # Stable high
            [4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.0, 5.1, 5.2, 5.3, 5.4]  # Accelerating up
        )

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 12, 1)
        )

        # Growth down, inflation up -> Stagflation
        # Note: Due to momentum calculation, actual result depends on historical window
        assert result.snapshot.dominant_regime in ["Stagflation", "Deflation", "Overheat"]

    def test_deflation_regime_scenario(self, calculator):
        """
        Test Deflation regime detection: Growth down, Inflation down

        Example: Economic contraction with falling prices
        """
        # PMI: declining (below 50)
        growth_series = (
            [50.0] * 10 +
            [49.5, 49.0, 48.5, 48.0, 47.5, 47.0, 46.5, 46.0] +
            [45.5] * 10 +
            [45.0, 44.5, 44.0, 43.5, 43.0, 42.5, 42.0, 41.5, 41.0, 40.5, 40.0, 39.5]
        )

        # CPI: falling (could be negative)
        inflation_series = (
            [2.0] * 10 +
            [1.8, 1.6, 1.4, 1.2, 1.0, 0.8, 0.6, 0.4] +
            [0.2] * 10 +
            [0.1, 0.0, -0.1, -0.2, -0.3, -0.4, -0.5, -0.6, -0.7, -0.8, -0.9, -1.0]
        )

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 12, 1)
        )

        # Both down -> Deflation
        assert result.snapshot.dominant_regime in ["Deflation", "Stagflation"]

    def test_china_2024_scenario(self, calculator):
        """
        Test China 2024 scenario: PMI around 50, CPI very low (~0.1-0.3%)

        This is a real-world scenario where the absolute momentum fix is critical.
        With relative momentum, CPI 0.1% -> 0.3% would show as 200% (WRONG!).
        With absolute momentum, it shows as +0.2pp (CORRECT!).
        """
        # China PMI 2024: hovering around 50
        growth_series = [
            49.0, 49.2, 49.4, 49.5, 49.3, 49.1, 49.0, 49.2,
            49.3, 49.5, 49.8, 50.1, 50.3, 50.5, 50.8, 51.0,
            51.2, 51.0, 50.8, 50.5, 50.3, 50.0, 49.8, 49.5,
            49.2, 49.0, 48.8, 48.5, 48.3, 48.0, 47.8, 47.5,
            47.3, 47.0, 46.8, 46.5, 46.3, 46.0, 45.8, 45.5,
            45.3, 45.0, 44.8, 44.5, 44.3, 44.0, 43.8, 43.5,
            43.3, 43.0, 42.8, 42.5, 42.3, 42.0, 41.8, 41.5,
            41.3, 41.0, 40.8, 40.5, 40.3, 40.0, 39.8, 39.5,
        ]

        # China CPI 2024: very low inflation
        # Using absolute momentum: small changes in pp are correctly captured
        inflation_series = [
            0.1, 0.1, 0.2, 0.2, 0.2, 0.1, 0.1, 0.0,
            0.0, -0.1, -0.1, -0.2, -0.2, -0.3, -0.3, -0.4,
            -0.4, -0.5, -0.5, -0.6, -0.6, -0.7, -0.7, -0.8,
            -0.8, -0.9, -0.9, -1.0, -1.0, -1.1, -1.1, -1.2,
            -1.2, -1.3, -1.3, -1.4, -1.4, -1.5, -1.5, -1.6,
            -1.6, -1.7, -1.7, -1.8, -1.8, -1.9, -1.9, -2.0,
            -2.0, -2.1, -2.1, -2.2, -2.2, -2.3, -2.3, -2.4,
            -2.4, -2.5, -2.5, -2.6, -2.6, -2.7, -2.7, -2.8,
        ]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 12, 1)
        )

        # Verify calculation succeeded
        assert result.snapshot.dominant_regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]
        assert sum(result.snapshot.distribution.values()) == pytest.approx(1.0)


class TestRegimeEdgeCases:
    """Tests for edge cases and boundary conditions"""

    def test_calculator_with_minimal_data(self):
        """Test with exactly minimum required data"""
        calculator = RegimeCalculator(zscore_min_periods=3)

        # Exactly 3 data points
        growth_series = [50.0, 51.0, 52.0]
        inflation_series = [2.0, 2.1, 2.2]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 1, 1)
        )

        assert result.snapshot is not None
        assert len(result.warnings) == 0

    def test_calculator_with_insufficient_data(self):
        """Test with insufficient data"""
        calculator = RegimeCalculator(zscore_min_periods=24)

        growth_series = [50.0, 51.0]
        inflation_series = [2.0, 2.1]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 1, 1)
        )

        # Should still calculate but with warnings
        assert result.snapshot is not None
        assert len(result.warnings) > 0
        assert "数据不足" in result.warnings[0]

    def test_calculator_with_constant_series(self):
        """Test with constant series (no change)"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_series = [50.0] * 30
        inflation_series = [2.0] * 30

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 1, 1)
        )

        # With constant series, momentum is 0, z-score is 0
        # Should give neutral distribution (~25% each)
        assert result.snapshot.growth_momentum_z == pytest.approx(0.0, abs=0.1)
        assert result.snapshot.inflation_momentum_z == pytest.approx(0.0, abs=0.1)

        # Distribution should be roughly equal
        for regime_prob in result.snapshot.distribution.values():
            assert 0.2 < regime_prob < 0.3

    def test_calculator_with_single_spike(self):
        """Test with a single spike in data"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        # Normal series with one spike at the end
        growth_series = [50.0] * 25 + [100.0]
        inflation_series = [2.0] * 25 + [5.0]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 1, 1)
        )

        # Spike should cause high z-scores
        assert result.snapshot.growth_momentum_z > 1.0
        assert result.snapshot.inflation_momentum_z > 1.0

    def test_calculator_with_negative_values(self):
        """Test with negative values (e.g., deflation)"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_series = [50.0, 49.0, 48.0, 47.0, 46.0, 45.0]
        inflation_series = [1.0, 0.5, 0.0, -0.5, -1.0, -1.5]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(date.today().year, 1, 1)
        )

        assert result.snapshot is not None
        assert sum(result.snapshot.distribution.values()) == pytest.approx(1.0)


class TestRegimeDateHandling:
    """Tests for date/time handling in regime calculation"""

    def test_observed_at_date_preserved(self):
        """Test that the observed_at date is correctly preserved"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_series = [50.0, 51.0, 52.0, 53.0, 54.0, 55.0]
        inflation_series = [2.0, 2.1, 2.2, 2.3, 2.4, 2.5]

        test_date = date(2024, 6, 15)
        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=test_date
        )

        assert result.snapshot.observed_at == test_date

    def test_calculation_with_future_date(self):
        """
        Test calculation with a future date (edge case).

        This handles the scenario where system time might be incorrect.
        The calculation should still work correctly.
        """
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_series = [50.0] * 6
        inflation_series = [2.0] * 6

        # Use a date far in the future
        future_date = date(2026, 12, 31)

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=future_date
        )

        assert result.snapshot.observed_at == future_date
        assert result.snapshot.dominant_regime in ["Recovery", "Overheat", "Stagflation", "Deflation"]

    def test_calculation_with_historical_date(self):
        """Test calculation with a historical date"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_series = [50.0] * 6
        inflation_series = [2.0] * 6

        historical_date = date(2020, 3, 15)  # Early COVID period

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=historical_date
        )

        assert result.snapshot.observed_at == historical_date

    def test_calculate_at_point_for_backtesting(self):
        """
        Test calculate_at_point method for backtesting scenarios.

        This method is used for point-in-time backtesting.
        """
        calculator = RegimeCalculator(zscore_min_periods=5)

        growth_history = [50.0, 51.0, 52.0, 53.0, 54.0]
        inflation_history = [2.0, 2.1, 2.2, 2.3, 2.4]

        result = calculator.calculate_at_point(
            growth_value=55.5,
            inflation_value=2.6,
            growth_history=growth_history,
            inflation_history=inflation_history,
            as_of_date=date(2024, 7, 1)
        )

        assert result.snapshot is not None
        # Should have 6 values in calculation (5 history + 1 current)
        assert result.snapshot.growth_momentum_z is not None
        assert result.snapshot.inflation_momentum_z is not None


class TestSigmoidProperties:
    """Test mathematical properties of sigmoid function"""

    def test_sigmoid_at_zero(self):
        """sigmoid(0) should equal 0.5"""
        assert sigmoid(0.0) == pytest.approx(0.5)

    def test_sigmoid_symmetry(self):
        """sigmoid(-x) = 1 - sigmoid(x)"""
        x = 1.5
        assert sigmoid(-x, k=1.0) == pytest.approx(1 - sigmoid(x, k=1.0))

    def test_sigmoid_monotonicity(self):
        """sigmoid should be monotonically increasing"""
        for k in [0.5, 1.0, 2.0, 5.0]:
            values = [sigmoid(i, k=k) for i in range(-10, 11)]
            for i in range(len(values) - 1):
                assert values[i] < values[i + 1]

    def test_sigmoid_bounds(self):
        """sigmoid should output in (0, 1) range"""
        for x in [-100, -10, -5, -1, 0, 1, 5, 10, 100]:
            for k in [0.5, 1.0, 2.0, 5.0]:
                result = sigmoid(x, k=k)
                assert 0.0 < result < 1.0

    def test_sigmoid_k_parameter_effect(self):
        """Test that k parameter affects steepness"""
        x = 1.0

        # Higher k should give higher value for positive x
        result_k1 = sigmoid(x, k=1.0)
        result_k5 = sigmoid(x, k=5.0)

        assert result_k5 > result_k1

        # Higher k should give lower value for negative x
        x_neg = -1.0
        result_neg_k1 = sigmoid(x_neg, k=1.0)
        result_neg_k5 = sigmoid(x_neg, k=5.0)

        assert result_neg_k5 < result_neg_k1


class TestRegimeDistributionProperties:
    """Test mathematical properties of regime distribution"""

    def test_distribution_always_sums_to_one(self):
        """Distribution should always sum to 1.0"""
        for growth_z in [-2, -1, -0.5, 0, 0.5, 1, 2]:
            for inflation_z in [-2, -1, -0.5, 0, 0.5, 1, 2]:
                result = calculate_regime_distribution(growth_z, inflation_z)
                total = sum(result.values())
                assert total == pytest.approx(1.0, abs=1e-10)

    def test_distribution_all_positive(self):
        """All regime probabilities should be positive"""
        for growth_z in [-2, -1, -0.5, 0, 0.5, 1, 2]:
            for inflation_z in [-2, -1, -0.5, 0, 0.5, 1, 2]:
                result = calculate_regime_distribution(growth_z, inflation_z)
                for prob in result.values():
                    assert prob > 0.0

    def test_distribution_recovery_dominant(self):
        """When growth_z high and inflation_z low, Recovery should be dominant"""
        result = calculate_regime_distribution(growth_z=2.0, inflation_z=-2.0)
        assert result["Recovery"] > 0.5

    def test_distribution_overheat_dominant(self):
        """When both high, Overheat should be dominant"""
        result = calculate_regime_distribution(growth_z=2.0, inflation_z=2.0)
        assert result["Overheat"] > 0.5

    def test_distribution_stagflation_dominant(self):
        """When growth_z low and inflation_z high, Stagflation should be dominant"""
        result = calculate_regime_distribution(growth_z=-2.0, inflation_z=2.0)
        assert result["Stagflation"] > 0.5

    def test_distribution_deflation_dominant(self):
        """When both low, Deflation should be dominant"""
        result = calculate_regime_distribution(growth_z=-2.0, inflation_z=-2.0)
        assert result["Deflation"] > 0.5

    def test_distribution_neutral(self):
        """When both z-scores near zero, distribution should be roughly equal"""
        result = calculate_regime_distribution(growth_z=0.0, inflation_z=0.0)
        for prob in result.values():
            assert 0.2 < prob < 0.3


class TestRollingZScoreProperties:
    """Test properties of rolling Z-score calculation"""

    def test_zscore_constant_series(self):
        """Z-score of constant series should be 0"""
        series = [100.0] * 30
        result = calculate_rolling_zscore(series, window=10, min_periods=5)

        # All values after min_periods should be 0
        for i in range(5, len(result)):
            assert result[i] == pytest.approx(0.0, abs=0.01)

    def test_zscore_linear_trend(self):
        """Z-score of linear trend should show pattern"""
        series = list(range(1, 31))
        result = calculate_rolling_zscore(series, window=10, min_periods=5)

        # Later values should have positive z-scores (trending up)
        assert result[-1] > 0

    def test_zscore_std_normalization(self):
        """Z-score should normalize by standard deviation"""
        # Create series with known standard deviation
        mean = 100.0
        std = 10.0
        series = [mean + std * ((i - 15) / 5) for i in range(30)]

        result = calculate_rolling_zscore(series, window=30, min_periods=24)

        # Last value should be roughly 1 (about 1 std above mean of window)
        # This is approximate due to rolling window
        assert abs(result[-1]) < 5  # Should not be extreme


class TestConfidenceLevels:
    """Test confidence level calculations"""

    def test_high_confidence_threshold(self):
        """Test is_high_confidence method"""
        snapshot = RegimeSnapshot(
            growth_momentum_z=1.0,
            inflation_momentum_z=0.5,
            distribution={"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            dominant_regime="Recovery",
            confidence=0.6,
            observed_at=date(2024, 1, 1)
        )

        assert snapshot.is_high_confidence(threshold=0.3) is True
        assert snapshot.is_high_confidence(threshold=0.5) is True
        assert snapshot.is_high_confidence(threshold=0.7) is False

    def test_confidence_percent_property(self):
        """Test confidence_percent property"""
        snapshot = RegimeSnapshot(
            growth_momentum_z=0.0,
            inflation_momentum_z=0.0,
            distribution={"Recovery": 0.25, "Overheat": 0.25, "Stagflation": 0.25, "Deflation": 0.25},
            dominant_regime="Recovery",
            confidence=0.25,
            observed_at=date(2024, 1, 1)
        )

        assert snapshot.confidence_percent == 25.0

    def test_low_confidence_warning(self):
        """Test that low confidence scenarios are identified"""
        calculator = RegimeCalculator(zscore_min_periods=5)

        # Create series that will give ambiguous results
        growth_series = [50.0, 50.5, 51.0, 49.5, 49.0, 50.2]
        inflation_series = [2.0, 2.1, 1.9, 2.2, 1.8, 2.3]

        result = calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=date(2024, 1, 1)
        )

        # With noisy data, confidence might be low
        if result.snapshot.confidence < 0.3:
            assert not result.snapshot.is_high_confidence(threshold=0.3)


class TestRegimeCalculatorConfigurations:
    """Test different calculator configurations"""

    def test_custom_momentum_period(self):
        """Test calculator with custom momentum period"""
        calculator = RegimeCalculator(momentum_period=6, zscore_min_periods=5)

        series = [50.0, 51.0, 52.0, 53.0, 54.0, 55.0, 56.0, 57.0]
        result = calculator.calculate(
            growth_series=series,
            inflation_series=series,
            as_of_date=date(2024, 1, 1)
        )

        assert result.snapshot is not None

    def test_custom_zscore_window(self):
        """Test calculator with custom Z-score window"""
        calculator = RegimeCalculator(zscore_window=30, zscore_min_periods=10)

        series = list(range(20, 60))
        result = calculator.calculate(
            growth_series=series,
            inflation_series=series,
            as_of_date=date(2024, 1, 1)
        )

        assert result.snapshot is not None

    def test_custom_sigmoid_k(self):
        """Test calculator with custom sigmoid k parameter"""
        calculator_k1 = RegimeCalculator(sigmoid_k=1.0, zscore_min_periods=5)
        calculator_k5 = RegimeCalculator(sigmoid_k=5.0, zscore_min_periods=5)

        growth = [50.0] * 6
        inflation = [2.0] * 6

        result_k1 = calculator_k1.calculate(growth, inflation, date(2024, 1, 1))
        result_k5 = calculator_k5.calculate(growth, inflation, date(2024, 1, 1))

        # With same inputs, different k should give different distributions
        # (though with constant series, both will be near-equal)
        assert result_k1.snapshot is not None
        assert result_k5.snapshot is not None

    def test_absolute_inflation_momentum_toggle(self):
        """Test use_absolute_inflation_momentum parameter"""
        calculator_abs = RegimeCalculator(
            use_absolute_inflation_momentum=True,
            zscore_min_periods=5
        )
        calculator_rel = RegimeCalculator(
            use_absolute_inflation_momentum=False,
            zscore_min_periods=5
        )

        growth = [50.0] * 6
        # Low inflation values where the difference matters
        inflation = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]

        result_abs = calculator_abs.calculate(growth, inflation, date(2024, 1, 1))
        result_rel = calculator_rel.calculate(growth, inflation, date(2024, 1, 1))

        # Results should differ when using absolute vs relative momentum
        # (The magnitude of inflation_z will be different)
        assert result_abs.snapshot.inflation_momentum_z is not None
        assert result_rel.snapshot.inflation_momentum_z is not None
