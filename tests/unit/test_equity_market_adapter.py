from datetime import date

import pytest

from apps.data_center.infrastructure.models import MacroFactModel
from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter


@pytest.mark.django_db
def test_market_data_repository_adapter_uses_reporting_period_for_index_returns():
    MacroFactModel.objects.create(
        indicator_code="000300.SH",
        reporting_period=date(2026, 3, 19),
        revision_number=1,
        value=100.0,
        unit="点",
        source="test",
        extra={"period_type": "D", "original_unit": "点"},
    )
    MacroFactModel.objects.create(
        indicator_code="000300.SH",
        reporting_period=date(2026, 3, 20),
        revision_number=1,
        value=102.0,
        unit="点",
        source="test",
        extra={"period_type": "D", "original_unit": "点"},
    )

    adapter = MarketDataRepositoryAdapter()

    returns = adapter.get_index_daily_returns(
        "000300.SH",
        start_date=date(2026, 3, 19),
        end_date=date(2026, 3, 20),
    )

    assert returns == {date(2026, 3, 20): 0.02}
