from apps.equity.application.market_sessions import (
    get_equity_detail_market_session_profile,
)


class _FakeStockRepository:
    def __init__(self, exchange: str) -> None:
        self.exchange = exchange

    def get_listing_exchange(self, stock_code: str) -> str:
        return self.exchange


def test_market_session_profile_uses_exchange_specific_timezone_and_sessions() -> None:
    payload = get_equity_detail_market_session_profile(
        "700.HK",
        stock_repository=_FakeStockRepository("HKEX"),
    )

    assert payload["exchange"] == "HKEX"
    assert payload["timezone"] == "Asia/Hong_Kong"
    assert payload["sessions"] == [
        {"start": "09:30", "end": "12:00"},
        {"start": "13:00", "end": "16:00"},
    ]
    assert payload["default_timeframe_in_session"] == "intraday"
    assert payload["default_timeframe_out_of_session"] == "day"


def test_market_session_profile_supports_us_markets() -> None:
    payload = get_equity_detail_market_session_profile(
        "AAPL",
        stock_repository=_FakeStockRepository("NASDAQ"),
    )

    assert payload["exchange"] == "NASDAQ"
    assert payload["timezone"] == "America/New_York"
    assert payload["sessions"] == [{"start": "09:30", "end": "16:00"}]


def test_market_session_profile_falls_back_to_non_intraday_default_for_unknown_market() -> None:
    payload = get_equity_detail_market_session_profile(
        "UNKNOWN",
        stock_repository=_FakeStockRepository("UNMAPPED"),
    )

    assert payload["exchange"] == "OTHER"
    assert payload["timezone"] == "UTC"
    assert payload["sessions"] == []
    assert payload["default_timeframe_out_of_session"] == "day"
