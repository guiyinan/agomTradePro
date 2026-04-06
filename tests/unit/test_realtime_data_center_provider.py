from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.data_center.infrastructure.models import PriceBarModel, QuoteSnapshotModel
from apps.realtime.infrastructure.repositories import DataCenterPriceDataProvider


@pytest.mark.django_db
def test_data_center_price_provider_prefers_quote_snapshot():
    QuoteSnapshotModel.objects.create(
        asset_code="000001.SZ",
        snapshot_at=datetime(2026, 4, 5, 9, 31, tzinfo=timezone.utc),
        current_price=Decimal("12.34"),
        volume=1000,
        source="eastmoney-main",
    )
    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 4, 4),
        freq="1d",
        adjustment="none",
        open=Decimal("12.00"),
        high=Decimal("12.50"),
        low=Decimal("11.80"),
        close=Decimal("12.20"),
        source="tushare-main",
    )

    provider = DataCenterPriceDataProvider()
    price = provider.get_realtime_price("000001.SZ")

    assert price is not None
    assert float(price.price) == 12.34
    assert price.source == "eastmoney-main"


@pytest.mark.django_db
def test_data_center_price_provider_falls_back_to_latest_bar():
    PriceBarModel.objects.create(
        asset_code="510300.SH",
        bar_date=date(2026, 4, 4),
        freq="1d",
        adjustment="none",
        open=Decimal("4.95"),
        high=Decimal("5.05"),
        low=Decimal("4.90"),
        close=Decimal("5.00"),
        source="tushare-main",
    )

    provider = DataCenterPriceDataProvider()
    price = provider.get_realtime_price("510300.SH")

    assert price is not None
    assert float(price.price) == 5.0
    assert price.source == "tushare-main"
