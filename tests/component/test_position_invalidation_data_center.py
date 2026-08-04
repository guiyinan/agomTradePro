from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel
from apps.simulated_trading.application import position_invalidation_checker as checker_module
from apps.simulated_trading.application.position_invalidation_checker import (
    _DataCenterMacroGateway,
)


@pytest.mark.django_db
def test_position_invalidation_gateway_reads_macro_facts_from_data_center(monkeypatch):
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2026, 3, 31),
        value=50.5,
        unit="%",
        source="akshare",
        revision_number=0,
        quality="valid",
    )

    monkeypatch.setattr(
        checker_module,
        "get_published_macro_fact_series",
        lambda code, limit: {
            "rows": [
                {
                    "indicator_code": code,
                    "reporting_period": "2026-02-28",
                    "value": 50.1,
                    "unit": "%",
                },
                {
                    "indicator_code": code,
                    "reporting_period": "2026-03-31",
                    "value": 50.5,
                    "unit": "%",
                },
            ],
            "must_not_use_for_decision": False,
        },
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2026, 2, 28),
        value=50.1,
        unit="%",
        source="akshare",
        revision_number=0,
        quality="valid",
    )

    gateway = _DataCenterMacroGateway()
    latest = gateway.get_latest_by_code("CN_PMI")
    history = gateway.get_history_by_code("CN_PMI", periods=12)

    assert latest is not None
    assert latest.value == 50.5
    assert len(history) == 2
    assert history[0].observed_at == date(2026, 3, 31)
