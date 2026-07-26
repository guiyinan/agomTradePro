"""Regime ORM model contract regressions."""

import pytest

from apps.regime.infrastructure.models import RegimeLog, RiskParameterConfigModel


@pytest.mark.parametrize(
    ("regime", "expected_label"),
    [
        ("Recovery", "复苏"),
        ("Overheat", "过热"),
        ("Stagflation", "滞胀"),
        ("Deflation", "通缩"),
    ],
)
def test_regime_log_uses_native_chinese_display_labels(
    regime: str,
    expected_label: str,
) -> None:
    log = RegimeLog(dominant_regime=regime)

    assert log.get_dominant_regime_display() == expected_label


@pytest.mark.parametrize("json_value", [{}, []])
def test_risk_parameter_preserves_empty_json_configuration(
    json_value: object,
) -> None:
    config = RiskParameterConfigModel(value_json=json_value)

    assert config.get_value() == json_value
