from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from apps.data_center.application.price_service import UnifiedPriceService
from core.exceptions import DataFetchError


def test_normalize_asset_code_handles_bare_exchange_codes():
    service = UnifiedPriceService()

    assert service.normalize_asset_code("159915") == "159915.SZ"
    assert service.normalize_asset_code("510300") == "510300.SH"
    assert service.normalize_asset_code("600519") == "600519.SH"
    assert service.normalize_asset_code("430001") == "430001.BJ"


def test_get_price_uses_historical_capability():
    service = UnifiedPriceService()
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_bars.return_value = [
        SimpleNamespace(
            asset_code="510300.SH",
            bar_date=date(2026, 3, 20),
            open=4.9,
            high=5.0,
            low=4.8,
            close=4.95,
            source="eastmoney",
        )
    ]
    result = service.get_price_result("510300", trade_date=date(2026, 3, 20))

    assert result is not None
    assert result.normalized_code == "510300.SH"
    assert result.price == 4.95
    assert result.freshness == "historical"


def test_get_latest_price_prefers_realtime_quote():
    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.return_value = SimpleNamespace(
        asset_code="159915.SZ",
        current_price=2.18,
        source="eastmoney",
    )
    result = service.get_price_result("159915")

    assert result is not None
    assert result.normalized_code == "159915.SZ"
    assert result.price == 2.18
    assert result.freshness == "realtime"


def test_get_latest_price_falls_back_to_recent_close():
    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.return_value = None
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_latest.return_value = SimpleNamespace(
        asset_code="510300.SH",
        bar_date=date(2026, 3, 20),
        open=4.9,
        high=5.0,
        low=4.8,
        close=4.95,
        source="eastmoney",
    )
    result = service.get_price_result("510300")

    assert result is not None
    assert result.price == 4.95
    assert result.freshness == "close_fallback"
    assert result.is_fallback is True


def test_exchange_traded_etf_does_not_fallback_to_fund_nav():
    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.return_value = None
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_latest.return_value = None
    service._get_fund_nav_price = Mock(return_value=None)

    result = service.get_price_result("510300")

    assert result is None
    service._get_fund_nav_price.assert_not_called()


def test_require_price_raises_when_all_sources_missing():
    service = UnifiedPriceService()
    service._dc_price_repo = Mock()
    service._dc_price_repo.get_bars.return_value = []

    try:
        service.require_price("510300", trade_date=date(2026, 3, 20))
        raise AssertionError("expected DataFetchError")
    except DataFetchError as exc:
        assert exc.code == "PRICE_UNAVAILABLE"
        assert exc.details["requested_code"] == "510300"
        assert exc.details["normalized_code"] == "510300.SH"
        assert exc.details["trade_date"] == "2026-03-20"


def test_get_latest_price_prefers_data_center_quote():
    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.return_value = SimpleNamespace(
        asset_code="159915.SZ",
        current_price=2.18,
        volume=1000,
        amount=2180.0,
        high=2.2,
        low=2.15,
        open=2.16,
        prev_close=2.1,
        source="dc_eastmoney",
        snapshot_at=datetime(2026, 3, 20, 9, 31, tzinfo=UTC),
    )

    result = service.get_price_result("159915")

    assert result is not None
    assert result.price == 2.18
    assert result.source == "dc_eastmoney"


def test_fund_price_can_read_from_data_center_nav():
    service = UnifiedPriceService()
    service._dc_fund_nav_repo = Mock()
    service._dc_fund_nav_repo.get_latest.return_value = SimpleNamespace(
        fund_code="110011",
        nav=1.2345,
        nav_date=date(2026, 3, 20),
        source="dc_tushare",
    )

    result = service.get_price_result("110011", asset_type="fund")

    assert result is not None
    assert result.price == 1.2345
    assert result.source == "dc_tushare"
    assert result.freshness == "close_fallback"


def test_realtime_quote_failure_returns_none_and_logs_debug(caplog):
    service = UnifiedPriceService()
    service._dc_quote_repo = Mock()
    service._dc_quote_repo.get_latest.side_effect = RuntimeError("quote backend offline")

    with caplog.at_level("DEBUG"):
        result = service._get_realtime_quote("159915.SZ")

    assert result is None
    assert "Realtime quote lookup failed" in caplog.text
