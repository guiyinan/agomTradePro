from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure.models import PriceBarModel
from apps.equity.infrastructure.repositories import DjangoStockRepository


@pytest.mark.django_db
def test_get_daily_prices_reads_canonical_cache():
    PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 3, 20),
        freq="1d",
        adjustment="none",
        open=Decimal("10.00"),
        high=Decimal("10.50"),
        low=Decimal("9.80"),
        close=Decimal("10.20"),
        volume=1000,
        amount=Decimal("10000"),
        source="test",
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
        "_get_remote_daily_prices",
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
def test_get_daily_prices_consumes_data_center_history(monkeypatch):
    repository = DjangoStockRepository()
    stock_code = "TEST0001.SZ"

    monkeypatch.setattr(repository._dc_price_bar_repo, "get_bars", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        repository,
        "_get_remote_historical_bars",
        lambda stock_code, start_date, end_date: [
            SimpleNamespace(trade_date=date(2026, 3, 20), close="10.20"),
            SimpleNamespace(trade_date=date(2026, 3, 21), close="10.50"),
        ],
    )

    prices = repository.get_daily_prices(stock_code, date(2026, 3, 1), date(2026, 3, 31))

    assert prices == [
        (date(2026, 3, 20), Decimal("10.20")),
        (date(2026, 3, 21), Decimal("10.50")),
    ]


def test_remote_history_storage_is_owned_by_data_center(monkeypatch):
    repository = DjangoStockRepository()
    from apps.data_center.domain.model_market_data import ModelDailyBar

    row = ModelDailyBar(
        "600000.SH", date(2026, 3, 20), 10, 11, 9, 10.2, 1000, 2.0, 1.0, "configured-route"
    )
    monkeypatch.setattr(
        "apps.equity.infrastructure.market_data_repository.get_model_market_data_port",
        lambda: SimpleNamespace(stock_history=lambda *args: (row,)),
    )
    monkeypatch.setattr(
        repository._dc_price_bar_repo,
        "bulk_upsert",
        lambda *_: pytest.fail("consumer must not persist the same source rows again"),
    )
    result = repository._get_remote_historical_bars(
        "600000.SH", date(2026, 3, 1), date(2026, 3, 31)
    )
    assert result == [row]
    assert result[0].amount is None


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
    monkeypatch.setattr(
        repository, "_get_remote_historical_bars", lambda *args, **kwargs: remote_bars
    )

    bars = repository.get_technical_bars(stock_code, date(2026, 1, 1), date(2026, 5, 1))

    assert len(bars) == len(remote_bars)
    assert bars[0].trade_date == date(2026, 1, 2)
