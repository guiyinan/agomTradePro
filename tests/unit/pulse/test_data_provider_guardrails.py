from datetime import date

from apps.pulse.infrastructure.data_provider import DjangoPulseDataProvider


def test_pulse_data_provider_blocks_cumulative_level_direct_inputs(monkeypatch):
    provider = DjangoPulseDataProvider()

    monkeypatch.setattr(
        provider,
        "_get_indicator_extra",
        lambda code: {
            "series_semantics": "cumulative_level",
            "pulse_input_policy": "derive_required",
        },
    )

    rows = provider._load_data_center_series("CN_GDP", date(2026, 5, 7))

    assert rows == []
