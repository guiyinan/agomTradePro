from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure.models import PriceBarModel
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
    stock_code = "TEST0001.SZ"

    monkeypatch.setattr(repository._dc_price_bar_repo, "get_bars", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        repository,
        "_get_tushare_gateway_daily_prices",
        lambda stock_code, start_date, end_date: [
            (date(2026, 3, 20), Decimal("10.20")),
            (date(2026, 3, 21), Decimal("10.50")),
        ],
    )

    prices = repository.get_daily_prices(stock_code, date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [
        (date(2026, 3, 20), Decimal("10.20")),
        (date(2026, 3, 21), Decimal("10.50")),
    ]


@pytest.mark.django_db
def test_get_daily_prices_falls_back_to_akshare_when_tushare_unavailable(monkeypatch):
    repository = DjangoStockRepository()
    stock_code = "TEST0001.SZ"

    monkeypatch.setattr(repository._dc_price_bar_repo, "get_bars", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        repository,
        "_get_tushare_gateway_daily_prices",
        lambda stock_code, start_date, end_date: [],
    )
    monkeypatch.setattr(
        repository,
        "_get_akshare_gateway_historical_bars",
        lambda stock_code, start_date, end_date: [
            SimpleNamespace(trade_date=date(2026, 3, 20), close="10.20"),
            SimpleNamespace(trade_date=date(2026, 3, 21), close="10.50"),
        ],
    )
    monkeypatch.setattr(repository, "_cache_remote_historical_bars", lambda stock_code, bars: None)

    prices = repository.get_daily_prices(stock_code, date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [
        (date(2026, 3, 20), Decimal("10.20")),
        (date(2026, 3, 21), Decimal("10.50")),
    ]


@pytest.mark.django_db
def test_get_technical_bars_does_not_stop_at_sparse_data_center_cache(monkeypatch):
    repository = DjangoStockRepository()
    stock_code = "600031.SH"
    PriceBarModel.objects.create(
        asset_code=stock_code,
        bar_date=date(2026, 3, 20),
        open=Decimal("10.00"),
        high=Decimal("10.50"),
        low=Decimal("9.80"),
        close=Decimal("10.20"),
        volume=1000,
        amount=Decimal("10000"),
        source="test",
    )

    remote_bars = [
        SimpleNamespace(
            trade_date=date(2026, 1, day),
            open="10.00",
            high="10.50",
            low="9.80",
            close=str(10 + day / 100),
            volume=1000,
            amount="10000",
        )
        for day in range(2, 27)
    ]
    monkeypatch.setattr(repository, "_get_remote_historical_bars", lambda *args, **kwargs: remote_bars)
    monkeypatch.setattr(repository, "_cache_remote_historical_bars", lambda *args, **kwargs: None)

    bars = repository.get_technical_bars(stock_code, date(2026, 1, 1), date(2026, 5, 1))

    assert len(bars) == len(remote_bars)
    assert bars[0].trade_date == date(2026, 1, 2)
