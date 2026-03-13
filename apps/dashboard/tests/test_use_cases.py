from apps.dashboard.application.use_cases import _normalize_regime_distribution


def test_normalize_regime_distribution_returns_zeroes_without_real_distribution():
    distribution = _normalize_regime_distribution("Deflation", None)

    assert distribution["Deflation"] == 0.0
    assert distribution["Recovery"] == 0.0
    assert distribution["Overheat"] == 0.0
    assert distribution["Stagflation"] == 0.0


def test_normalize_regime_distribution_preserves_existing_values():
    distribution = _normalize_regime_distribution(
        "Deflation",
        {
            "Recovery": 0.1,
            "Overheat": 0.2,
            "Deflation": 0.3,
            "Stagflation": 0.4,
        },
    )

    assert distribution == {
        "Recovery": 0.1,
        "Overheat": 0.2,
        "Deflation": 0.3,
        "Stagflation": 0.4,
    }
