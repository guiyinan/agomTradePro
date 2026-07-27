"""Tests for the Simulated Trading canonical price adapter."""

from datetime import date
from unittest.mock import Mock

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.data_center.application.price_service import PriceLookupResult
from apps.simulated_trading.infrastructure.price_provider import DataCenterPriceProvider


def test_get_price_result_preserves_canonical_provenance() -> None:
    """The adapter must not replace Data Center source or observation metadata."""

    trade_date = date(2026, 7, 25)
    upstream = PriceLookupResult(
        requested_code="000001.SZ",
        normalized_code="000001.SZ",
        price=12.5,
        as_of=trade_date,
        source="tushare_daily",
        freshness="historical",
        is_fallback=False,
    )
    price_service = Mock()
    price_service.get_price_result.return_value = upstream
    provider = DataCenterPriceProvider.__new__(DataCenterPriceProvider)
    provider._price_service = price_service

    result = provider.get_price_result("000001.SZ", trade_date)

    assert result == MarketPriceResult(
        normalized_code="000001.SZ",
        price=12.5,
        as_of=trade_date,
        source="tushare_daily",
        freshness="historical",
        is_fallback=False,
    )
    price_service.get_price_result.assert_called_once_with(
        asset_code="000001.SZ",
        trade_date=trade_date,
    )


def test_get_price_result_preserves_unavailable_result() -> None:
    """An unavailable Data Center price remains unavailable."""

    price_service = Mock()
    price_service.get_price_result.return_value = None
    provider = DataCenterPriceProvider.__new__(DataCenterPriceProvider)
    provider._price_service = price_service

    assert provider.get_price_result("000001.SZ") is None
