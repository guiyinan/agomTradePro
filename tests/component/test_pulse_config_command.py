import pytest
from django.core.management import call_command

from apps.pulse.infrastructure.data_provider import DEFAULT_PULSE_INDICATORS
from apps.pulse.infrastructure.models import PulseIndicatorConfigModel


@pytest.mark.django_db
def test_init_pulse_config_force_deactivates_obsolete_indicator_configs():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="USD_INDEX",
        indicator_name="美元指数",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="zscore",
        bullish_threshold=-0.5,
        bearish_threshold=0.5,
        neutral_band=0.5,
        signal_multiplier=-0.25,
        is_active=True,
    )

    call_command("init_pulse_config", "--force")

    obsolete = PulseIndicatorConfigModel.objects.get(indicator_code="USD_INDEX")
    assert obsolete.is_active is False
    assert PulseIndicatorConfigModel.objects.filter(
        indicator_code="CN_PMI",
        is_active=True,
    ).exists()
    assert PulseIndicatorConfigModel.objects.filter(
        indicator_code="000300.SH",
        is_active=True,
    ).exists()


@pytest.mark.django_db
def test_init_pulse_config_force_matches_fallback_indicator_definitions():
    call_command("init_pulse_config", "--force")

    db_configs = {
        config.indicator_code: config
        for config in PulseIndicatorConfigModel.objects.filter(is_active=True)
    }
    assert set(db_configs) == {indicator.code for indicator in DEFAULT_PULSE_INDICATORS}
    for indicator in DEFAULT_PULSE_INDICATORS:
        config = db_configs[indicator.code]
        assert config.indicator_name == indicator.name
        assert config.dimension == indicator.dimension
        assert config.frequency == indicator.frequency
        assert config.weight == indicator.weight
        assert config.signal_type == indicator.signal_type
        assert config.bullish_threshold == indicator.bullish_threshold
        assert config.bearish_threshold == indicator.bearish_threshold
        assert config.neutral_band == indicator.neutral_band
        assert config.signal_multiplier == indicator.signal_multiplier
