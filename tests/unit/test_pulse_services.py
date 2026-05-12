"""Tests for Pulse Domain Services"""

from datetime import date

import pytest

from apps.pulse.domain.entities import (
    DimensionScore,
    PulseConfig,
    PulseIndicatorReading,
)
from apps.pulse.domain.services import (
    assess_regime_strength,
    calculate_dimension_score,
    calculate_pulse,
    detect_transition_warning,
)


def _make_reading(
    code: str = "TEST",
    dimension: str = "growth",
    signal_score: float = 0.5,
    weight: float = 1.0,
    is_stale: bool = False,
) -> PulseIndicatorReading:
    return PulseIndicatorReading(
        code=code,
        name=f"Test {code}",
        dimension=dimension,
        value=100.0,
        z_score=0.5,
        direction="improving",
        signal="bullish",
        signal_score=signal_score,
        weight=weight,
        data_age_days=1,
        is_stale=is_stale,
    )


class TestCalculateDimensionScore:
    """Test calculate_dimension_score()"""

    def test_single_indicator(self):
        """Single indicator → score equals its signal_score"""
        readings = [_make_reading(dimension="growth", signal_score=0.6)]
        result = calculate_dimension_score(readings, "growth")
        assert result.score == pytest.approx(0.6, abs=0.01)
        assert result.signal == "bullish"
        assert result.indicator_count == 1

    def test_multiple_indicators_weighted_average(self):
        """Multiple indicators → weighted average"""
        readings = [
            _make_reading(code="A", dimension="growth", signal_score=0.8, weight=2.0),
            _make_reading(code="B", dimension="growth", signal_score=0.2, weight=1.0),
        ]
        result = calculate_dimension_score(readings, "growth")
        # (0.8*2 + 0.2*1) / (2+1) = 1.8/3 = 0.6
        assert result.score == pytest.approx(0.6, abs=0.01)

    def test_stale_indicators_excluded(self):
        """Stale indicators should be excluded"""
        readings = [
            _make_reading(code="A", dimension="growth", signal_score=0.8, is_stale=False),
            _make_reading(code="B", dimension="growth", signal_score=-0.8, is_stale=True),
        ]
        result = calculate_dimension_score(readings, "growth")
        assert result.score == pytest.approx(0.8, abs=0.01)
        assert result.indicator_count == 1

    def test_no_valid_indicators(self):
        """No valid indicators → neutral score"""
        readings = [
            _make_reading(dimension="growth", signal_score=0.8, is_stale=True),
        ]
        result = calculate_dimension_score(readings, "growth")
        assert result.score == 0.0
        assert result.signal == "neutral"
        assert result.indicator_count == 0

    def test_ignores_other_dimensions(self):
        """Only considers indicators matching the requested dimension"""
        readings = [
            _make_reading(dimension="growth", signal_score=0.8),
            _make_reading(dimension="inflation", signal_score=-0.8),
        ]
        result = calculate_dimension_score(readings, "growth")
        assert result.score == pytest.approx(0.8, abs=0.01)

    def test_neutral_signal_classification(self):
        """Score between -0.2 and 0.2 → neutral"""
        readings = [_make_reading(dimension="liquidity", signal_score=0.1)]
        result = calculate_dimension_score(readings, "liquidity")
        assert result.signal == "neutral"

    def test_bearish_signal_classification(self):
        """Score < -0.2 → bearish"""
        readings = [_make_reading(dimension="sentiment", signal_score=-0.5)]
        result = calculate_dimension_score(readings, "sentiment")
        assert result.signal == "bearish"


class TestAssessRegimeStrength:
    """Test assess_regime_strength()"""

    def test_strong_above_03(self):
        assert assess_regime_strength(0.5) == "strong"
        assert assess_regime_strength(0.31) == "strong"

    def test_moderate_between_neg03_and_03(self):
        assert assess_regime_strength(0.0) == "moderate"
        assert assess_regime_strength(0.29) == "moderate"
        assert assess_regime_strength(-0.29) == "moderate"

    def test_weak_below_neg03(self):
        assert assess_regime_strength(-0.5) == "weak"
        assert assess_regime_strength(-0.31) == "weak"


class TestDetectTransitionWarning:
    """Test detect_transition_warning()"""

    def test_recovery_growth_and_liquidity_weak(self):
        """Recovery: growth + liquidity both weak → Deflation warning"""
        dim_scores = [
            DimensionScore("growth", -0.5, "bearish", 2, ""),
            DimensionScore("inflation", 0, "neutral", 2, ""),
            DimensionScore("liquidity", -0.5, "bearish", 2, ""),
            DimensionScore("sentiment", 0, "neutral", 2, ""),
        ]
        warning, direction, reasons = detect_transition_warning(
            dim_scores, "Recovery", PulseConfig.defaults()
        )
        assert warning is True
        assert direction == "Deflation"

    def test_recovery_inflation_strong(self):
        """Recovery: inflation strong → Overheat warning"""
        dim_scores = [
            DimensionScore("growth", 0.5, "bullish", 2, ""),
            DimensionScore("inflation", 0.5, "bullish", 2, ""),
            DimensionScore("liquidity", 0, "neutral", 2, ""),
            DimensionScore("sentiment", 0, "neutral", 2, ""),
        ]
        warning, direction, reasons = detect_transition_warning(
            dim_scores, "Recovery", PulseConfig.defaults()
        )
        assert warning is True
        assert direction == "Overheat"

    def test_stable_regime_no_warning(self):
        """All neutral → no warning"""
        dim_scores = [
            DimensionScore("growth", 0, "neutral", 2, ""),
            DimensionScore("inflation", 0, "neutral", 2, ""),
            DimensionScore("liquidity", 0, "neutral", 2, ""),
            DimensionScore("sentiment", 0, "neutral", 2, ""),
        ]
        warning, direction, reasons = detect_transition_warning(
            dim_scores, "Recovery", PulseConfig.defaults()
        )
        assert warning is False
        assert direction is None

    def test_deflation_improvement(self):
        """Deflation: growth + liquidity both improving → Recovery warning"""
        dim_scores = [
            DimensionScore("growth", 0.5, "bullish", 2, ""),
            DimensionScore("inflation", 0, "neutral", 2, ""),
            DimensionScore("liquidity", 0.5, "bullish", 2, ""),
            DimensionScore("sentiment", 0, "neutral", 2, ""),
        ]
        warning, direction, reasons = detect_transition_warning(
            dim_scores, "Deflation", PulseConfig.defaults()
        )
        assert warning is True
        assert direction == "Recovery"


class TestCalculatePulse:
    """Test calculate_pulse() end-to-end"""

    def test_basic_calculation(self):
        """Calculate pulse with mixed readings"""
        readings = [
            _make_reading("A", "growth", 0.5),
            _make_reading("B", "inflation", -0.3),
            _make_reading("C", "liquidity", 0.2),
            _make_reading("D", "sentiment", 0.1),
        ]
        snapshot = calculate_pulse(readings, "Recovery", date(2026, 3, 23))

        assert snapshot.observed_at == date(2026, 3, 23)
        assert snapshot.regime_context == "Recovery"
        assert len(snapshot.dimension_scores) == 4
        assert -1 <= snapshot.composite_score <= 1
        assert snapshot.regime_strength in ("strong", "moderate", "weak")
        assert snapshot.data_source == "calculated"

    def test_stale_data_flagged(self):
        """Stale indicators → data_source = 'stale'"""
        readings = [
            _make_reading("A", "growth", 0.5, is_stale=True),
            _make_reading("B", "inflation", 0.3),
        ]
        snapshot = calculate_pulse(readings, "Recovery", date(2026, 3, 23))
        assert snapshot.data_source == "stale"
        assert snapshot.stale_indicator_count == 1
        assert not snapshot.is_reliable

    def test_all_bullish_strong(self):
        """All bullish → strong regime"""
        readings = [
            _make_reading("A", "growth", 0.8),
            _make_reading("B", "inflation", 0.7),
            _make_reading("C", "liquidity", 0.6),
            _make_reading("D", "sentiment", 0.9),
        ]
        snapshot = calculate_pulse(readings, "Recovery", date(2026, 3, 23))
        assert snapshot.composite_score > 0.3
        assert snapshot.regime_strength == "strong"

    def test_all_bearish_weak(self):
        """All bearish → weak regime"""
        readings = [
            _make_reading("A", "growth", -0.8),
            _make_reading("B", "inflation", -0.7),
            _make_reading("C", "liquidity", -0.6),
            _make_reading("D", "sentiment", -0.9),
        ]
        snapshot = calculate_pulse(readings, "Recovery", date(2026, 3, 23))
        assert snapshot.composite_score < -0.3
        assert snapshot.regime_strength == "weak"

    def test_dimension_dict_property(self):
        """dimension_dict property returns {dimension: score}"""
        readings = [
            _make_reading("A", "growth", 0.5),
            _make_reading("B", "inflation", -0.3),
        ]
        snapshot = calculate_pulse(readings, "Recovery", date(2026, 3, 23))
        dd = snapshot.dimension_dict
        assert "growth" in dd
        assert "inflation" in dd
        assert dd["growth"] == pytest.approx(0.5, abs=0.01)
