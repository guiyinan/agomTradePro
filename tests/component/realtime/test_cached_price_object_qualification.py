"""Qualify each cached value independently, even when codes repeat."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pytest_mock import MockerFixture

from apps.realtime.domain.entities import AssetType, RealtimePrice
from apps.realtime.infrastructure.publication_price_cache import currently_qualified_cache_prices


def _quote() -> RealtimePrice:
    """Return an explicitly publication-bound fixture, without querying any database."""
    observed = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    return RealtimePrice(
        asset_code="000001.SZ",
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=observed,
        fetched_at=observed + timedelta(seconds=1),
        source="vendor-fixture",
        cache_source_kind="data_center_publication",
        publication_id="current-quote-fixture",
        publication_dataset_key="equity.quote.snapshot",
        publication_key="current",
    )


def _published_quote(mocker: MockerFixture, price: RealtimePrice) -> None:
    """Stub only the public quote read while exercising real qualification."""
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value={
            "publication_id": price.publication_id,
            "dataset_key": price.publication_dataset_key,
            "publication_key": "current",
            "must_not_use_for_decision": False,
            "rows": [
                {
                    "asset_code": price.asset_code,
                    "current_price": float(price.price),
                    "snapshot_at": price.timestamp.isoformat(),
                    "fetched_at": price.fetched_at.isoformat() if price.fetched_at else None,
                    "source": price.source,
                    "volume": price.volume,
                }
            ],
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        side_effect=AssertionError("These quote/external cases must not read daily bars"),
    )


@pytest.mark.parametrize("reverse_order", [False, True])
@pytest.mark.parametrize("invalid_field", ["price", "publication_id", "provenance"])
def test_duplicate_cache_object_qualification(
    mocker: MockerFixture, reverse_order: bool, invalid_field: str
) -> None:
    """A qualified code cannot confer its proof on a different input object."""
    valid = _quote()
    _published_quote(mocker, valid)
    if invalid_field == "price":
        invalid = replace(valid, price=Decimal("99.99"))
    elif invalid_field == "publication_id":
        invalid = replace(valid, publication_id="retired-quote-fixture")
    else:
        invalid = replace(valid, cache_source_kind=None)
    prices = [invalid, valid] if reverse_order else [valid, invalid]
    result = currently_qualified_cache_prices(prices)
    assert len(result) == 1
    assert result[0] is valid


@pytest.mark.parametrize("reverse_order", [False, True])
def test_external_cache_does_not_qualify_unknown_same_code(
    mocker: MockerFixture, reverse_order: bool
) -> None:
    """Explicit external provenance never qualifies a same-code legacy row."""
    valid = replace(
        _quote(),
        cache_source_kind="external_provider",
        publication_id=None,
        publication_dataset_key=None,
        publication_key=None,
    )
    invalid = replace(valid, price=Decimal("99.99"), cache_source_kind=None)
    query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        side_effect=AssertionError("No publication lookup is expected for external/unknown rows"),
    )
    prices = [invalid, valid] if reverse_order else [valid, invalid]
    result = currently_qualified_cache_prices(prices)
    assert len(result) == 1
    assert result[0] is valid
    query.assert_not_called()


def test_qualified_cached_objects_preserve_input_order(mocker: MockerFixture) -> None:
    """Return qualified input objects in their original cross-source order."""
    quote = _quote()
    _published_quote(mocker, quote)
    external = replace(quote, asset_code="000002.SZ", cache_source_kind="external_provider")
    invalid = replace(quote, price=Decimal("99.99"))
    result = currently_qualified_cache_prices([invalid, external, quote])
    assert len(result) == 2
    assert result[0] is external
    assert result[1] is quote


@pytest.mark.parametrize("field", ["change", "change_pct"])
@pytest.mark.parametrize("value", [Decimal("0"), Decimal("1.23456789")])
def test_published_cache_rejects_unreported_change_values(
    mocker: MockerFixture, field: str, value: Decimal
) -> None:
    """The current published adapters expose no verified change metrics."""
    quote = _quote()
    _published_quote(mocker, quote)
    tampered = replace(quote, **{field: value})
    assert currently_qualified_cache_prices([tampered]) == []


def test_external_cache_keeps_explicit_change_metrics(mocker: MockerFixture) -> None:
    """Keep the existing external-provider contract, including a real zero."""
    price = replace(
        _quote(),
        cache_source_kind="external_provider",
        change=Decimal("0"),
        change_pct=Decimal("0"),
    )
    query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        side_effect=AssertionError("External provenance does not use this publication read"),
    )
    result = currently_qualified_cache_prices([price])
    assert result == [price]
    assert result[0] is price
    query.assert_not_called()


@pytest.mark.parametrize("change_pct", [None, Decimal("0")])
def test_bar_cache_keeps_only_source_proven_change_values(
    mocker: MockerFixture, change_pct: Decimal | None
) -> None:
    """The separate daily-bar reader accepts unknown metrics but rejects invented zero."""
    observed = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)
    price = replace(
        _quote(),
        timestamp=observed,
        fetched_at=None,
        source="vendor-bar",
        publication_dataset_key="equity.price.bar",
        publication_id="current-bar-fixture",
        change_pct=change_pct,
    )
    query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value={
            "publication_id": price.publication_id,
            "dataset_key": "equity.price.bar",
            "publication_key": "current",
            "must_not_use_for_decision": False,
            "rows": [
                {
                    "asset_code": price.asset_code,
                    "bar_date": observed.date().isoformat(),
                    "close": float(price.price),
                    "source": price.source,
                    "volume": price.volume,
                }
            ],
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        side_effect=AssertionError("Bar-only inputs must not read the quote publication"),
    )
    result = currently_qualified_cache_prices([price])
    assert result == ([price] if change_pct is None else [])
    if change_pct is None:
        assert result[0] is price
    query.assert_called_once_with(price.asset_code, publication_key="current", limit=1)
