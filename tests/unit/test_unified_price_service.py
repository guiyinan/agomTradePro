from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from apps.market_data.application.price_service import UnifiedPriceService
from apps.market_data.domain.entities import HistoricalPriceBar, QuoteSnapshot
from apps.market_data.domain.enums import DataCapability
from core.exceptions import DataFetchError


def test_normalize_asset_code_handles_bare_exchange_codes():
    service = UnifiedPriceService()

    assert service.normalize_asset_code("159915") == "159915.SZ"
    assert service.normalize_asset_code("510300") == "510300.SH"
    assert service.normalize_asset_code("600519") == "600519.SH"
    assert service.normalize_asset_code("430001") == "430001.BJ"


@patch("apps.market_data.application.price_service.get_registry")
def test_get_price_uses_historical_capability(mock_get_registry):
    registry = Mock()
    registry.call_with_failover.return_value = [
        HistoricalPriceBar(
            asset_code="510300.SH",
            trade_date=date(2026, 3, 20),
            open=4.9,
            high=5.0,
            low=4.8,
            close=4.95,
            source="eastmoney",
        )
    ]
    mock_get_registry.return_value = registry

    service = UnifiedPriceService()
    result = service.get_price_result("510300", trade_date=date(2026, 3, 20))

    assert result is not None
    assert result.normalized_code == "510300.SH"
    assert result.price == 4.95
    assert result.freshness == "historical"
    registry.call_with_failover.assert_called_once()
    assert registry.call_with_failover.call_args.args[0] == DataCapability.HISTORICAL_PRICE


@patch("apps.market_data.application.price_service.get_registry")
def test_get_latest_price_prefers_realtime_quote(mock_get_registry):
    registry = Mock()
    registry.call_with_failover.return_value = [
        QuoteSnapshot(
            stock_code="159915.SZ",
            price=Decimal("2.18"),
            source="eastmoney",
        )
    ]
    mock_get_registry.return_value = registry

    service = UnifiedPriceService()
    result = service.get_price_result("159915")

    assert result is not None
    assert result.normalized_code == "159915.SZ"
    assert result.price == 2.18
    assert result.freshness == "realtime"
    assert registry.call_with_failover.call_args.args[0] == DataCapability.REALTIME_QUOTE


@patch("apps.market_data.application.price_service.get_registry")
def test_get_latest_price_falls_back_to_recent_close(mock_get_registry):
    registry = Mock()
    registry.call_with_failover.side_effect = [
        None,
        [
            HistoricalPriceBar(
                asset_code="510300.SH",
                trade_date=date(2026, 3, 20),
                open=4.9,
                high=5.0,
                low=4.8,
                close=4.95,
                source="eastmoney",
            )
        ],
    ]
    mock_get_registry.return_value = registry

    service = UnifiedPriceService()
    result = service.get_price_result("510300")

    assert result is not None
    assert result.price == 4.95
    assert result.freshness == "close_fallback"
    assert result.is_fallback is True


@patch("apps.market_data.application.price_service.get_registry")
def test_exchange_traded_etf_does_not_fallback_to_fund_nav(mock_get_registry):
    registry = Mock()
    registry.call_with_failover.return_value = None
    mock_get_registry.return_value = registry

    service = UnifiedPriceService()
    service._get_fund_nav_price = Mock(return_value=None)

    result = service.get_price_result("510300")

    assert result is None
    service._get_fund_nav_price.assert_not_called()


@patch("apps.market_data.application.price_service.get_registry")
def test_require_price_raises_when_all_sources_missing(mock_get_registry):
    registry = Mock()
    registry.call_with_failover.return_value = None
    mock_get_registry.return_value = registry

    service = UnifiedPriceService()

    try:
        service.require_price("510300", trade_date=date(2026, 3, 20))
        raise AssertionError("expected DataFetchError")
    except DataFetchError as exc:
        assert exc.code == "PRICE_UNAVAILABLE"
        assert exc.details["requested_code"] == "510300"
        assert exc.details["normalized_code"] == "510300.SH"
        assert exc.details["trade_date"] == "2026-03-20"
