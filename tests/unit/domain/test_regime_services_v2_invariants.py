"""Regime V2 finite-input and output-contract regressions."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from apps.regime.domain.services_v2 import (
    RegimeCalculationResult,
    RegimeCalculatorV2,
    RegimeType,
    ThresholdConfig,
    TrendIndicator,
    calculate_momentum_simple,
    calculate_regime_by_level,
    calculate_regime_distribution_by_level,
    calculate_zscore_simple,
    classify_momentum_strength,
    generate_prediction,
)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("pmi_expansion", float("nan")),
        ("pmi_contraction", float("inf")),
        ("cpi_high", float("-inf")),
        ("momentum_weight", True),
        ("high_confidence_threshold", float("nan")),
    ],
)
def test_threshold_config_rejects_non_finite_or_boolean_values(
    field_name: str,
    invalid_value: object,
) -> None:
    """Damaged database thresholds cannot enter the Domain calculator."""

    values: dict[str, object] = {field_name: invalid_value}
    with pytest.raises(ValueError, match=field_name):
        ThresholdConfig(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "config",
    [
        ThresholdConfig(pmi_contraction=50.0, pmi_expansion=50.0),
        ThresholdConfig(cpi_deflation=0.0, cpi_low=1.0, cpi_high=2.0),
    ],
)
def test_threshold_config_accepts_ordered_boundaries(config: ThresholdConfig) -> None:
    """Equal PMI split and ordered CPI bands remain valid configuration."""

    assert isinstance(config, ThresholdConfig)


def test_threshold_config_rejects_inverted_bands_and_out_of_range_weights() -> None:
    """Threshold order and normalized weights are enforced at construction."""

    with pytest.raises(ValueError, match="pmi_contraction"):
        ThresholdConfig(pmi_contraction=51.0, pmi_expansion=50.0)
    with pytest.raises(ValueError, match="CPI thresholds"):
        ThresholdConfig(cpi_deflation=1.5, cpi_low=1.0, cpi_high=2.0)
    with pytest.raises(ValueError, match="momentum_weight"):
        ThresholdConfig(momentum_weight=1.01)
    with pytest.raises(ValueError, match="high_confidence_threshold"):
        ThresholdConfig(high_confidence_threshold=-0.01)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), True])
def test_level_classification_and_distribution_reject_invalid_observations(
    invalid_value: object,
) -> None:
    """Non-finite or boolean macro observations fail before regime publication."""

    with pytest.raises(ValueError, match="pmi_value"):
        calculate_regime_by_level(invalid_value, 1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cpi_value"):
        calculate_regime_distribution_by_level(50.0, invalid_value)  # type: ignore[arg-type]


def test_distribution_remains_normalized_for_extreme_finite_observations() -> None:
    """Distance overflow degrades to a finite uniform distribution."""

    distribution = calculate_regime_distribution_by_level(1e308, -1e308)

    assert set(distribution) == {regime.value for regime in RegimeType}
    assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in distribution.values())
    assert math.isclose(math.fsum(distribution.values()), 1.0)


@pytest.mark.parametrize("period", [0, -1, True, 1.5])
def test_momentum_rejects_invalid_period(period: object) -> None:
    """Invalid lookback periods cannot change Python indexing semantics."""

    with pytest.raises(ValueError, match="period"):
        calculate_momentum_simple([49.0, 50.0], period=period)  # type: ignore[arg-type]


def test_momentum_returns_integer_direction_and_rejects_non_finite_history() -> None:
    """Direction matches the public integer contract and history stays finite."""

    _, direction = calculate_momentum_simple([49.0, 49.5, 50.0], period=2)
    assert type(direction) is int
    with pytest.raises(ValueError, match=r"series\[1\]"):
        calculate_momentum_simple([49.0, float("nan"), 50.0], period=2)


def test_zscore_and_strength_reject_non_finite_values() -> None:
    """NaN cannot silently classify as strong momentum."""

    with pytest.raises(ValueError, match=r"series\[1\]"):
        calculate_zscore_simple([1.0, float("inf"), 2.0], 2.0)
    with pytest.raises(ValueError, match="z_score"):
        classify_momentum_strength(float("nan"))


def test_trend_and_prediction_contracts_reject_unknown_classifications() -> None:
    """Published trend labels and direction codes use finite enumerated values."""

    with pytest.raises(ValueError, match="direction"):
        TrendIndicator("PMI", 50.0, 0.1, 0.2, "sideways", "weak")
    with pytest.raises(ValueError, match="pmi_trend"):
        generate_prediction(RegimeType.RECOVERY, 2, 0, [])


def test_calculator_rejects_non_finite_history_and_datetime_asof() -> None:
    """The main calculator fails closed before producing misleading evidence."""

    calculator = RegimeCalculatorV2()
    with pytest.raises(ValueError, match=r"pmi_series\[1\]"):
        calculator.calculate(
            [49.0, float("nan"), 50.0],
            [1.0, 1.1, 1.2],
            date(2026, 1, 31),
        )
    with pytest.raises(ValueError, match="as_of_date"):
        calculator.calculate(
            [49.0, 50.0],
            [1.0, 1.1],
            datetime(2026, 1, 31, tzinfo=UTC),
        )


def test_result_rejects_non_normalized_distribution() -> None:
    """Consumers never receive a finite-looking confidence with invalid probabilities."""

    with pytest.raises(ValueError, match="sum to 1"):
        RegimeCalculationResult(
            regime=RegimeType.RECOVERY,
            confidence=0.4,
            growth_level=51.0,
            inflation_level=1.0,
            growth_state="expansion",
            inflation_state="low",
            distribution={regime.value: 0.1 for regime in RegimeType},
            trend_indicators=[],
        )
