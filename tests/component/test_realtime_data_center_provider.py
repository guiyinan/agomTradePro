from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.data_center.infrastructure.models import PriceBarModel, QuoteSnapshotModel
from apps.realtime.infrastructure.repositories import DataCenterPriceDataProvider


@pytest.mark.django_db
def test_data_center_price_provider_prefers_published_quote_snapshot(mocker):
    QuoteSnapshotModel.objects.create(
        asset_code="000001.SZ",
        snapshot_at=datetime(2026, 4, 5, 9, 31, tzinfo=UTC),
        fetched_at=datetime(2026, 4, 5, 9, 32, tzinfo=UTC),
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
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_quote_payloads",
        return_value={
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "snapshot_at": "2026-04-05T09:31:00+00:00",
                    "fetched_at": "2026-04-05T09:32:00+00:00",
                    "current_price": 12.34,
                    "volume": 1000,
                    "source": "eastmoney-main",
                }
            ],
            "must_not_use_for_decision": False,
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_price_bar_series",
        return_value={"rows": [], "must_not_use_for_decision": True},
    )

    provider = DataCenterPriceDataProvider()
    price = provider.get_realtime_price("000001.SZ")

    assert price is not None
    assert float(price.price) == 12.34
    assert price.source == "eastmoney-main"


@pytest.mark.django_db
def test_data_center_price_provider_blocks_unpublished_latest_bar(mocker):
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
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_quote_payloads",
        return_value={
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_price_bar_series",
        return_value={
            "rows": [],
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        },
    )

    provider = DataCenterPriceDataProvider()
    price = provider.get_realtime_price("510300.SH")

    assert price is None


def test_data_center_price_provider_blocks_stale_published_facts(mocker):
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_quote_payloads",
        return_value={
            "rows": [],
            "must_not_use_for_decision": True,
            "freshness_status": "stale",
            "blocked_reason": "canonical_publication_stale",
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.repositories.get_published_price_bar_series",
        return_value={
            "rows": [],
            "must_not_use_for_decision": True,
            "freshness_status": "stale",
            "blocked_reason": "canonical_publication_stale",
        },
    )

    price = DataCenterPriceDataProvider().get_realtime_price("510300.SH")

    assert price is None
