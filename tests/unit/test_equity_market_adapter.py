from datetime import date

import pytest

from apps.data_center.infrastructure.models import PriceBarModel
from apps.equity.infrastructure.adapters import MarketDataRepositoryAdapter


@pytest.mark.django_db
def test_market_data_repository_adapter_uses_reporting_period_for_index_returns():
    PriceBarModel.objects.create(
        asset_code="000300.SH",
        bar_date=date(2026, 3, 19),
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        source="test",
    )
    PriceBarModel.objects.create(
        asset_code="000300.SH",
        bar_date=date(2026, 3, 20),
        open=102.0,
        high=102.0,
        low=102.0,
        close=102.0,
        source="test",
    )

    adapter = MarketDataRepositoryAdapter()

    returns = adapter.get_index_daily_returns(
        "000300.SH",
        start_date=date(2026, 3, 19),
        end_date=date(2026, 3, 20),
    )

    assert returns == {date(2026, 3, 20): 0.02}
