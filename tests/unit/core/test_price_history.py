from datetime import date
from types import SimpleNamespace

from core.integration.price_history import fetch_close_prices_from_data_center


class _FakePriceBarRepository:
    def get_bars(self, asset_code: str, *, start: date, end: date):
        assert asset_code == "510300.SH"
        assert start < end
        return [
            SimpleNamespace(close="4.90"),
            SimpleNamespace(close="5.00"),
            SimpleNamespace(close="5.10"),
        ]


def test_fetch_close_prices_from_data_center_uses_price_bar_repository(monkeypatch):
    monkeypatch.setattr(
        "core.integration.price_history.PriceBarRepository",
        lambda: _FakePriceBarRepository(),
    )

    assert fetch_close_prices_from_data_center("510300.SH", date(2026, 4, 26), 2) == [5.0, 5.1]
