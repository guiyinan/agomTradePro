import pytest

from apps.pulse.domain.entities import PulseIndicatorReading
from apps.pulse.domain.services import calculate_dimension_score


def _reading(dimension: str, score: float, weight: float = 1.0, is_stale: bool = False):
    return PulseIndicatorReading(
        code=f"{dimension}-{score}",
        name="test",
        dimension=dimension,
        value=1.0,
        z_score=score,
        direction="stable",
        signal="neutral",
        signal_score=score,
        weight=weight,
        data_age_days=1,
        is_stale=is_stale,
    )


def test_dimension_score_uses_weighted_average():
    result = calculate_dimension_score(
        [_reading("growth", 0.8, 2.0), _reading("growth", 0.2, 1.0)],
        "growth",
    )

    assert result.score == pytest.approx(0.6, abs=0.01)
    assert result.signal == "bullish"


def test_dimension_score_returns_neutral_when_weight_is_zero():
    result = calculate_dimension_score(
        [_reading("sentiment", 0.7, 0.0)],
        "sentiment",
    )

    assert result.score == 0.0
    assert result.signal == "neutral"


def test_dimension_score_excludes_stale_readings():
    result = calculate_dimension_score(
        [_reading("liquidity", -0.6, is_stale=True), _reading("liquidity", 0.4)],
        "liquidity",
    )

    assert result.score == pytest.approx(0.4, abs=0.01)
    assert result.indicator_count == 1
