from apps.pulse.domain.entities import DimensionScore, PulseConfig
from apps.pulse.domain.services import detect_transition_warning


def _scores(growth: float, inflation: float, liquidity: float, sentiment: float = 0.0):
    return [
        DimensionScore("growth", growth, "neutral", 1, ""),
        DimensionScore("inflation", inflation, "neutral", 1, ""),
        DimensionScore("liquidity", liquidity, "neutral", 1, ""),
        DimensionScore("sentiment", sentiment, "neutral", 1, ""),
    ]


def test_overheat_growth_weak_warns_stagflation():
    warning, direction, reasons = detect_transition_warning(
        _scores(-0.4, 0.2, 0.0),
        "Overheat",
        PulseConfig.defaults(),
    )

    assert warning is True
    assert direction == "Stagflation"
    assert reasons


def test_stagflation_inflation_falls_with_growth_weak_warns_deflation():
    warning, direction, reasons = detect_transition_warning(
        _scores(-0.5, -0.4, 0.0),
        "Stagflation",
        PulseConfig.defaults(),
    )

    assert warning is True
    assert direction == "Deflation"
    assert "增长仍弱" in reasons


def test_deflation_without_broad_improvement_has_no_warning():
    warning, direction, reasons = detect_transition_warning(
        _scores(0.4, 0.1, -0.1),
        "Deflation",
        PulseConfig.defaults(),
    )

    assert warning is False
    assert direction is None
    assert reasons == []
