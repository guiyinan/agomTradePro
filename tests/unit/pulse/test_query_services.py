from datetime import date

from apps.pulse.application import query_services
from apps.pulse.domain.entities import PulseIndicatorReading


def test_pulse_indicator_display_uses_governed_unit_and_plain_language(monkeypatch) -> None:
    """Count indicators expose their governed unit and a readable interpretation."""

    monkeypatch.setattr(
        query_services,
        "get_macro_runtime_metadata",
        lambda: {
            "CN_A_LIMIT_UP_COUNT": {
                "unit": "家",
                "default_unit": "家",
            }
        },
    )
    reading = PulseIndicatorReading(
        code="CN_A_LIMIT_UP_COUNT",
        name="A股涨停家数",
        dimension="sentiment",
        value=37.0,
        z_score=0.1,
        direction="stable",
        signal="neutral",
        signal_score=0.0,
        weight=1.0,
        data_age_days=0,
        is_stale=False,
        observed_at=date(2026, 8, 14),
        source_kind="macro_fact",
    )

    payload = query_services.build_pulse_indicator_display_payloads([reading])

    assert payload[reading.code] == {
        "unit": "家",
        "value_display": "37 家",
        "signal_label": "中性",
        "direction_label": "近期稳定",
        "interpretation": "中性；近期稳定",
    }
