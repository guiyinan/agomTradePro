"""Quote observation and fetch timestamps must remain distinct."""

from datetime import UTC, datetime
from decimal import Decimal

from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
from apps.realtime.infrastructure.repositories import AKSharePriceDataProvider


def test_gateway_quote_times_are_preserved_in_realtime_and_storage_dtos() -> None:
    observed_at = datetime(2026, 7, 31, 7, 0, tzinfo=UTC)
    fetched_at = datetime(2026, 7, 31, 7, 0, 3, tzinfo=UTC)
    gateway_quote = QuoteSnapshot(
        stock_code="002156.SZ",
        price=Decimal("56.73"),
        source="tencent",
        observed_at=observed_at,
        fetched_at=fetched_at,
    )
    provider = AKSharePriceDataProvider()

    realtime = provider._build_price_from_quote_snapshot("002156.SZ", gateway_quote)
    stored = provider._build_market_quote_snapshot("002156.SZ", gateway_quote)

    assert realtime is not None
    assert realtime.timestamp is observed_at
    assert stored is not None
    assert stored.snapshot_at is observed_at
    assert stored.fetched_at is fetched_at


def test_gateway_quote_without_observation_time_is_not_published_as_realtime() -> None:
    gateway_quote = QuoteSnapshot(
        stock_code="002156.SZ",
        price=Decimal("56.73"),
        source="unknown",
    )
    provider = AKSharePriceDataProvider()

    assert provider._build_price_from_quote_snapshot("002156.SZ", gateway_quote) is None
    assert provider._build_market_quote_snapshot("002156.SZ", gateway_quote) is None
