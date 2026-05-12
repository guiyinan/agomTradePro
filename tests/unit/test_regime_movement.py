"""Tests for Regime Movement Assessment"""


from apps.regime.domain.navigator_services import assess_regime_movement
from apps.regime.domain.services_v2 import RegimeType, TrendIndicator


def _make_trend(code: str, direction: str, strength: str = "moderate", momentum_z: float = 0.5) -> TrendIndicator:
    return TrendIndicator(
        indicator_code=code,
        current_value=50.0,
        momentum=0.01,
        momentum_z=momentum_z,
        direction=direction,
        strength=strength,
    )


class TestAssessRegimeMovement:
    """Test assess_regime_movement()"""

    def test_stable_when_trends_consistent_with_recovery(self):
        """Recovery + PMI up + CPI stable → stable"""
        trends = [
            _make_trend("PMI", "up", "moderate"),
            _make_trend("CPI", "flat", "weak"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, trends)
        assert direction == "stable"
        assert target is None
        assert prob == 0.0

    def test_recovery_pmi_down_cpi_up_transitions_to_stagflation(self):
        """Recovery + PMI down + CPI up → transition to Stagflation"""
        trends = [
            _make_trend("PMI", "down", "moderate", -0.5),
            _make_trend("CPI", "up", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, trends)
        assert direction == "transitioning"
        assert target == "Stagflation"
        assert prob == 0.4
        assert any("CPI 上行" in r for r in reasons)

    def test_recovery_pmi_down_only_transitions_to_deflation(self):
        """Recovery + PMI down + CPI flat → transition to Deflation"""
        trends = [
            _make_trend("PMI", "down", "moderate", -0.5),
            _make_trend("CPI", "flat", "weak"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, trends)
        assert direction == "transitioning"
        assert target == "Deflation"
        assert prob == 0.3

    def test_recovery_cpi_strong_up_transitions_to_overheat(self):
        """Recovery + CPI strong up → transition to Overheat"""
        trends = [
            _make_trend("PMI", "up", "moderate"),
            _make_trend("CPI", "up", "strong"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, trends)
        assert direction == "transitioning"
        assert target == "Overheat"
        assert prob == 0.35

    def test_overheat_pmi_down_transitions_to_stagflation(self):
        """Overheat + PMI down → transition to Stagflation"""
        trends = [
            _make_trend("PMI", "down", "moderate"),
            _make_trend("CPI", "up", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.OVERHEAT, trends)
        assert direction == "transitioning"
        assert target == "Stagflation"
        assert prob == 0.35

    def test_overheat_cpi_down_transitions_to_recovery(self):
        """Overheat + CPI moderate down → transition to Recovery"""
        trends = [
            _make_trend("PMI", "up", "moderate"),
            _make_trend("CPI", "down", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.OVERHEAT, trends)
        assert direction == "transitioning"
        assert target == "Recovery"
        assert prob == 0.3

    def test_stagflation_cpi_down_pmi_down_transitions_to_deflation(self):
        """Stagflation + CPI down + PMI down → transition to Deflation"""
        trends = [
            _make_trend("PMI", "down", "moderate"),
            _make_trend("CPI", "down", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.STAGFLATION, trends)
        assert direction == "transitioning"
        assert target == "Deflation"
        assert prob == 0.35

    def test_stagflation_cpi_down_pmi_stable_transitions_to_recovery(self):
        """Stagflation + CPI down + PMI stable → transition to Recovery"""
        trends = [
            _make_trend("PMI", "flat", "weak"),
            _make_trend("CPI", "down", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.STAGFLATION, trends)
        assert direction == "transitioning"
        assert target == "Recovery"
        assert prob == 0.3

    def test_deflation_pmi_up_cpi_flat_transitions_to_recovery(self):
        """Deflation + PMI up + CPI flat → transition to Recovery"""
        trends = [
            _make_trend("PMI", "up", "moderate"),
            _make_trend("CPI", "flat", "weak"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.DEFLATION, trends)
        assert direction == "transitioning"
        assert target == "Recovery"
        assert prob == 0.4

    def test_deflation_pmi_up_cpi_up_transitions_to_overheat(self):
        """Deflation + PMI up + CPI up → transition to Overheat"""
        trends = [
            _make_trend("PMI", "up", "moderate"),
            _make_trend("CPI", "up", "moderate"),
        ]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.DEFLATION, trends)
        assert direction == "transitioning"
        assert target == "Overheat"
        assert prob == 0.3

    def test_insufficient_data_returns_stable(self):
        """Only one trend indicator → stable"""
        trends = [_make_trend("PMI", "up", "moderate")]
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, trends)
        assert direction == "stable"
        assert "趋势数据不足" in reasons

    def test_empty_trends_returns_stable(self):
        """No trend indicators → stable"""
        direction, target, prob, reasons = assess_regime_movement(RegimeType.RECOVERY, [])
        assert direction == "stable"
        assert prob == 0.0
