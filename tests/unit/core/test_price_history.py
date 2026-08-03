from datetime import date

from core.integration.price_history import (
    fetch_close_prices_from_data_center,
    fetch_published_close_prices_from_data_center,
)


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


def test_fetch_published_close_prices_blocks_stale_publication(monkeypatch):
    monkeypatch.setattr(
        "core.integration.price_history.get_published_price_bar_series",
        lambda **kwargs: {
            "rows": [{"timestamp": "2026-01-01", "close": 5.0}],
            "publication_id": "pub-stale",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_stale",
        },
    )

    result = fetch_published_close_prices_from_data_center("510300.SH", date(2026, 8, 3), 2)

    assert result["prices"] == []
    assert result["must_not_use_for_decision"] is True
    assert result["blocked_reason"] == "canonical_publication_stale"


def test_fetch_published_close_prices_preserves_fresh_rows(monkeypatch):
    monkeypatch.setattr(
        "core.integration.price_history.get_published_price_bar_series",
        lambda **kwargs: {
            "rows": [
                {"timestamp": "2026-08-01", "close": 5.0},
                {"timestamp": "2026-08-02", "close": 5.1},
            ],
            "publication_id": "pub-fresh",
            "must_not_use_for_decision": False,
            "freshness_status": "fresh",
        },
    )

    result = fetch_published_close_prices_from_data_center("510300.SH", date(2026, 8, 3), 2)

    assert result["prices"] == [5.0, 5.1]
    assert result["publication_id"] == "pub-fresh"
    assert result["freshness_status"] == "fresh"
