from datetime import date

from core.integration.price_history import fetch_close_prices_from_data_center


def test_fetch_close_prices_from_data_center_uses_query_service(monkeypatch):
    def _fetch(*, asset_code: str, start_date: date, end_date: date):
        assert asset_code == "510300.SH"
        assert start_date < end_date
        return [4.9, 5.0, 5.1]

    monkeypatch.setattr(
        "core.integration.price_history._fetch_close_prices",
        _fetch,
    )

    assert fetch_close_prices_from_data_center("510300.SH", date(2026, 4, 26), 2) == [5.0, 5.1]
