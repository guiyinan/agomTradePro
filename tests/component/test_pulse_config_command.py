import pytest
from django.core.management import call_command

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
