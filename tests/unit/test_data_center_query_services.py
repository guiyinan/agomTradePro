from datetime import date
from types import SimpleNamespace

from apps.data_center.application import query_services


def test_fetch_close_prices_returns_oldest_to_newest(monkeypatch):
    """PriceBarRepository returns newest first; query service must normalize order."""

    class FakePriceRepository:
        def get_bars(self, asset_code, start=None, end=None, limit=500):
            assert asset_code == "510300"
            assert start == date(2026, 1, 1)
            assert end == date(2026, 1, 3)
            return [
                SimpleNamespace(close=10.3),
                SimpleNamespace(close=10.2),
                SimpleNamespace(close=10.1),
            ]

    monkeypatch.setattr(
        query_services,
        "get_price_bar_repository",
        lambda: FakePriceRepository(),
    )

    assert query_services.fetch_close_prices(
        asset_code="510300",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
    ) == [10.1, 10.2, 10.3]
