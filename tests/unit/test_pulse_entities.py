from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from apps.pulse.domain.entities import (
    DimensionScore,
    PulseConfig,
    PulseIndicatorReading,
    PulseSnapshot,
)


def test_pulse_snapshot_properties():
    snapshot = PulseSnapshot(
        observed_at=date(2026, 3, 24),
        regime_context="Recovery",
        dimension_scores=[DimensionScore("growth", 0.3, "bullish", 1, "增长脉搏偏强")],
        composite_score=0.3,
        regime_strength="moderate",
        transition_warning=False,
        transition_direction=None,
        transition_reasons=[],
        indicator_readings=[],
    )

    assert snapshot.is_reliable is True
    assert snapshot.dimension_dict == {"growth": 0.3}


def test_pulse_entities_are_frozen():
    reading = PulseIndicatorReading(
        code="PMI",
        name="制造业PMI",
        dimension="growth",
        value=50.0,
        z_score=0.0,
        direction="stable",
        signal="neutral",
        signal_score=0.0,
        weight=1.0,
        data_age_days=1,
        is_stale=False,
    )

    with pytest.raises(FrozenInstanceError):
        reading.value = 51.0


def test_pulse_config_defaults_are_equal_weight():
    config = PulseConfig.defaults()

    assert config.dimension_weights == {
        "growth": 0.25,
        "inflation": 0.25,
        "liquidity": 0.25,
        "sentiment": 0.25,
    }

    with pytest.raises(TypeError):
        config.dimension_weights["growth"] = 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bullish_z_threshold": float("nan")},
        {"bearish_z_threshold": 2.0, "bullish_z_threshold": 1.0},
        {"daily_stale_days": 0},
        {
            "dimension_weights": {
                "growth": 0.5,
                "inflation": 0.5,
                "liquidity": 0.5,
                "sentiment": 0.5,
            }
        },
    ],
)
def test_pulse_config_rejects_invalid_runtime_evidence(kwargs):
    with pytest.raises(ValueError):
        PulseConfig(**kwargs)
