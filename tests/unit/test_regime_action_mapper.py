"""Tests for Regime Action Mapper"""

from datetime import date

import pytest

from apps.regime.domain.action_mapper import (
    ActionMapperConfig,
    map_regime_pulse_to_action,
)


def _default_weight_ranges():
    return [
        {"category": "equity", "lower": 0.50, "upper": 0.70},
        {"category": "bond", "lower": 0.15, "upper": 0.30},
        {"category": "commodity", "lower": 0.05, "upper": 0.15},
        {"category": "cash", "lower": 0.05, "upper": 0.15},
    ]


class TestMapRegimePulseToAction:
    """Test map_regime_pulse_to_action()"""

    def test_positive_pulse_shifts_weights_upward(self):
        """Positive pulse score → proportional weight shift toward upper bound categories"""
        positive = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=["消费"],
            styles=["成长"],
            reasoning="test",
            pulse_composite_score=0.8,
            pulse_regime_strength="strong",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        negative = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=["消费"],
            styles=["成长"],
            reasoning="test",
            pulse_composite_score=-0.8,
            pulse_regime_strength="weak",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        # Commodity/cash have wider proportional ranges (0.05-0.15 = 3x),
        # so their normalized weight should shift more with pulse.
        assert positive.asset_weights["commodity"] > negative.asset_weights["commodity"]
        assert positive.asset_weights["cash"] > negative.asset_weights["cash"]
        # Both should still sum to 1
        assert sum(positive.asset_weights.values()) == pytest.approx(1.0, abs=0.01)
        assert sum(negative.asset_weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_neutral_pulse_takes_midpoint(self):
        """Zero pulse score → weights at midpoint"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=["消费"],
            styles=["成长"],
            reasoning="test",
            pulse_composite_score=0.0,
            pulse_regime_strength="moderate",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        # ratio=0.5, midpoint of range
        assert 0.55 < result.asset_weights["equity"] < 0.70

    def test_weights_sum_to_one(self):
        """Asset weights should always normalize to 1.0"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=0.5,
            pulse_regime_strength="moderate",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        total = sum(result.asset_weights.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_weak_pulse_reduces_risk_budget(self):
        """Weak pulse → risk budget multiplied by weak_risk_factor"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=-0.5,
            pulse_regime_strength="weak",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        assert result.risk_budget_pct < 0.85
        assert result.risk_budget_pct == pytest.approx(0.85 * 0.85, abs=0.01)

    def test_strong_pulse_increases_risk_budget_capped(self):
        """Strong pulse → risk budget increased but capped at max"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=0.5,
            pulse_regime_strength="strong",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        assert result.risk_budget_pct <= 0.95  # max cap

    def test_stagflation_generates_hedge_recommendation(self):
        """Stagflation → hedge recommendation for inflation"""
        result = map_regime_pulse_to_action(
            regime_name="Stagflation",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.50,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=0.0,
            pulse_regime_strength="moderate",
            confidence=0.7,
            as_of_date=date(2026, 3, 23),
        )
        assert result.hedge_recommendation is not None
        assert "通胀" in result.hedge_recommendation

    def test_deflation_weak_generates_hedge_recommendation(self):
        """Deflation + weak pulse → hedge recommendation"""
        result = map_regime_pulse_to_action(
            regime_name="Deflation",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.60,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=-0.5,
            pulse_regime_strength="weak",
            confidence=0.5,
            as_of_date=date(2026, 3, 23),
        )
        assert result.hedge_recommendation is not None
        assert "国债" in result.hedge_recommendation

    def test_recovery_moderate_no_hedge(self):
        """Recovery + moderate → no hedge"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=0.0,
            pulse_regime_strength="moderate",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        assert result.hedge_recommendation is None

    def test_explainability_fields_populated(self):
        """Regime contribution and pulse contribution texts are set"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=["消费"],
            styles=["成长"],
            reasoning="test",
            pulse_composite_score=0.3,
            pulse_regime_strength="moderate",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        assert "Recovery" in result.regime_contribution
        assert "权益区间" in result.regime_contribution
        assert "脉搏" in result.pulse_contribution
        assert "插值系数" in result.pulse_contribution

    def test_custom_config_overrides(self):
        """Custom ActionMapperConfig adjusts behavior"""
        config = ActionMapperConfig(
            weak_risk_factor=0.50,
            max_risk_budget=0.80,
            position_limit_high_risk=0.15,
            hedge_enabled=False,
        )
        result = map_regime_pulse_to_action(
            regime_name="Stagflation",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.50,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=-0.5,
            pulse_regime_strength="weak",
            confidence=0.5,
            as_of_date=date(2026, 3, 23),
            config=config,
        )
        # weak_risk_factor=0.50 → 0.50*0.50=0.25
        assert result.risk_budget_pct == pytest.approx(0.25, abs=0.01)
        # hedge disabled
        assert result.hedge_recommendation is None

    def test_extreme_pulse_score_clamped(self):
        """Pulse score > 1 or < -1 should be clamped"""
        result = map_regime_pulse_to_action(
            regime_name="Recovery",
            weight_ranges=_default_weight_ranges(),
            risk_budget=0.85,
            sectors=[],
            styles=[],
            reasoning="test",
            pulse_composite_score=2.0,  # > 1
            pulse_regime_strength="strong",
            confidence=0.8,
            as_of_date=date(2026, 3, 23),
        )
        # Should still produce valid weights
        total = sum(result.asset_weights.values())
        assert total == pytest.approx(1.0, abs=0.01)
