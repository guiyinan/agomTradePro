from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel, PriceBarModel
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


@pytest.mark.django_db
def test_pulse_data_provider_prefers_data_center_macro_facts_over_legacy():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="CN_PMI",
        indicator_name="制造业PMI",
        dimension="growth",
        frequency="monthly",
        weight=1.0,
        signal_type="level",
        bullish_threshold=52.0,
        bearish_threshold=48.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    MacroIndicator.objects.create(
        code="CN_PMI",
        value=45.0,
        unit="指数",
        original_unit="指数",
        reporting_period=date(2026, 4, 21),
        period_type="M",
        source="legacy",
        revision_number=1,
    )
    for day, value in [(19, 49.0), (20, 50.0), (21, 51.2)]:
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=date(2026, 4, day),
            value=value,
            unit="指数",
            source="AKShare Public",
            published_at=date(2026, 4, day),
            quality="valid",
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 4, 21))

    assert len(readings) == 1
    assert readings[0].code == "CN_PMI"
    assert readings[0].value == 51.2


@pytest.mark.django_db
def test_pulse_data_provider_reads_asset_code_from_data_center_price_bars():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="000300.SH",
        indicator_name="沪深300",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=4100.0,
        bearish_threshold=3500.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    for day, close in [(19, 3840.0), (20, 3880.0), (21, 3925.5)]:
        PriceBarModel.objects.create(
            asset_code="000300.SH",
            bar_date=date(2026, 4, day),
            open=3800.0,
            high=3950.0,
            low=3790.0,
            close=close,
            source="AKShare Public",
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 4, 21))

    assert len(readings) == 1
    assert readings[0].code == "000300.SH"
    assert readings[0].value == 3925.5
