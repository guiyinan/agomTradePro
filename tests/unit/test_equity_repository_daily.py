from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.equity.infrastructure.models import StockDailyModel
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
def test_get_daily_prices_prefers_local_cache():
    StockDailyModel.objects.create(
        stock_code="000001.SZ",
        trade_date=date(2026, 3, 20),
        open=Decimal("10.00"),
        high=Decimal("10.50"),
        low=Decimal("9.80"),
        close=Decimal("10.20"),
        volume=1000,
        amount=Decimal("10000"),
    )

    repository = DjangoStockRepository()

    prices = repository.get_daily_prices("000001.SZ", date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [(date(2026, 3, 20), Decimal("10.20"))]


@pytest.mark.django_db
def test_get_daily_prices_falls_back_to_remote_source_when_local_cache_missing(monkeypatch):
    repository = DjangoStockRepository()
    remote_frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-03-20", "2026-03-21"]),
            "close": ["10.20", "10.50"],
        }
    )

    monkeypatch.setattr(
        "apps.equity.infrastructure.repositories.TushareStockAdapter",
        lambda: SimpleNamespace(fetch_daily_data=lambda stock_code, start_date, end_date: remote_frame),
    )

    prices = repository.get_daily_prices("000001.SZ", date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [
        (date(2026, 3, 20), Decimal("10.20")),
        (date(2026, 3, 21), Decimal("10.50")),
    ]


@pytest.mark.django_db
def test_get_daily_prices_falls_back_to_akshare_when_tushare_unavailable(monkeypatch):
    repository = DjangoStockRepository()

    monkeypatch.setattr(
        repository,
        "_get_tushare_daily_prices",
        lambda stock_code, start_date, end_date: [],
    )
    monkeypatch.setattr(
        repository,
        "_get_akshare_daily_prices",
        lambda stock_code, start_date, end_date: [
            (date(2026, 3, 20), Decimal("10.20")),
            (date(2026, 3, 21), Decimal("10.50")),
        ],
    )

    prices = repository.get_daily_prices("000001.SZ", date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [
        (date(2026, 3, 20), Decimal("10.20")),
        (date(2026, 3, 21), Decimal("10.50")),
    ]
