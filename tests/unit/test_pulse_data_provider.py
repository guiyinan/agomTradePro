from datetime import date

import pytest

from apps.macro.infrastructure.models import MacroIndicator
from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider
from apps.pulse.infrastructure.models import PulseIndicatorConfigModel


@pytest.mark.django_db
def test_pulse_data_provider_reads_macro_indicator_records():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="CN_TERM_SPREAD_10Y2Y",
        indicator_name="国债利差(10Y-2Y)",
        dimension="growth",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=100.0,
        bearish_threshold=0.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )

    for idx, value in enumerate([60.0, 80.0, 110.0], start=1):
        MacroIndicator.objects.create(
            code="CN_TERM_SPREAD_10Y2Y",
            value=value,
            unit="bp",
            original_unit="bp",
            reporting_period=date(2026, 3, idx),
            period_type="D",
            source="manual",
            revision_number=1,
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 3, 3))

    assert len(readings) == 1
    assert readings[0].code == "CN_TERM_SPREAD_10Y2Y"
    assert readings[0].value == 110.0
