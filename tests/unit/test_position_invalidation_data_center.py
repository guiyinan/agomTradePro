from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel
from apps.simulated_trading.application.position_invalidation_checker import (
    _DataCenterMacroGateway,
)


@pytest.mark.django_db
def test_position_invalidation_gateway_reads_macro_facts_from_data_center():
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2026, 3, 31),
        value=50.5,
        unit="%",
        source="tushare-main",
        revision_number=0,
        quality="valid",
    )
    MacroFactModel.objects.create(
        indicator_code="CN_PMI",
        reporting_period=date(2026, 2, 28),
        value=50.1,
        unit="%",
        source="tushare-main",
        revision_number=0,
        quality="valid",
    )

    gateway = _DataCenterMacroGateway()
    latest = gateway.get_latest_by_code("CN_PMI")
    history = gateway.get_history_by_code("CN_PMI", periods=12)

    assert latest is not None
    assert latest.value == 50.5
    assert len(history) == 2
    assert history[-1].observed_at == date(2026, 3, 31)
