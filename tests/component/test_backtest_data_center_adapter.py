from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.backtest.infrastructure.adapters.composite_price_adapter import (
    DataCenterAssetPriceAdapter,
)
from apps.data_center.infrastructure.models import PriceBarModel


@pytest.mark.django_db
@patch(
    "apps.backtest.infrastructure.adapters.composite_price_adapter.get_asset_class_tickers",
    return_value={"a_share_core": "510300.SH"},
)
def test_backtest_data_center_adapter_reads_price_series(_mock_tickers):
    PriceBarModel.objects.bulk_create(
        [
            PriceBarModel(
                asset_code="510300.SH",
                bar_date=date(2026, 4, 3),
                freq="1d",
                adjustment="none",
                open=Decimal("4.90"),
                high=Decimal("5.00"),
                low=Decimal("4.85"),
                close=Decimal("4.95"),
                source="tushare-main",
            ),
            PriceBarModel(
                asset_code="510300.SH",
                bar_date=date(2026, 4, 4),
                freq="1d",
                adjustment="none",
                open=Decimal("4.95"),
                high=Decimal("5.05"),
                low=Decimal("4.90"),
                close=Decimal("5.00"),
                source="tushare-main",
            ),
        ]
    )

    adapter = DataCenterAssetPriceAdapter()
    price = adapter.get_price("a_share_core", date(2026, 4, 4))
    series = adapter.get_prices("a_share_core", date(2026, 4, 3), date(2026, 4, 4))

    assert price == 5.0
    assert len(series) == 2
    assert series[0].as_of_date == date(2026, 4, 3)
    assert series[1].price == 5.0
