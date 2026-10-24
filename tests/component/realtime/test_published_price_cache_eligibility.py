"""Current-publication eligibility for cached realtime Data Center prices."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from json import loads
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from apps.realtime.application.price_polling_service import PricePollingUseCase
from apps.realtime.domain.entities import AssetType, PricePollingConfig, RealtimePrice
from apps.realtime.infrastructure.repositories import (
    AKSharePriceDataProvider,
    DatabaseWatchlistProvider,
    DataCenterPriceDataProvider,
    RedisRealtimePriceRepository,
)

_ASSET_CODE = "000001.SZ"
_PUBLICATION_KEY = "current"
_QUOTE_DATASET = "equity.quote.snapshot"
_BAR_DATASET = "equity.price.bar"


@pytest.fixture
def isolated_realtime_cache():
    """Use a real Django cache backend isolated from other test cache keys."""

    settings = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ash04-realtime-publication-cache",
        }
    }
    with override_settings(CACHES=settings):
        cache.clear()
        yield
        cache.clear()


def _quote_payload(
    *,
    publication_id: str = "quote-pub-1",
    asset_code: str = _ASSET_CODE,
    observed_at: datetime,
    price: object = 12.34,
) -> dict[str, object]:
    """Build one response matching the public current-quote payload contract."""

    return {
        "rows": [
            {
                "asset_code": asset_code,
                "snapshot_at": observed_at.isoformat(),
                "fetched_at": (observed_at + timedelta(seconds=1)).isoformat(),
                "current_price": price,
                "volume": 1000,
                "source": "vendor-quote",
            }
        ],
        "publication_id": publication_id,
        "dataset_key": _QUOTE_DATASET,
        "publication_key": _PUBLICATION_KEY,
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
    }


def _blocked_quote_payload() -> dict[str, object]:
    return {
        "rows": [],
        "dataset_key": _QUOTE_DATASET,
        "publication_key": _PUBLICATION_KEY,
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
        "freshness_status": "blocked",
    }


def _use_case(repository: RedisRealtimePriceRepository) -> PricePollingUseCase:
    """Compose the real cache/application path with only provider fallback stubbed."""

    use_case = PricePollingUseCase.__new__(PricePollingUseCase)
    use_case.price_repository = repository
    use_case.price_provider = Mock()
    use_case.price_provider.get_realtime_prices_batch.return_value = []
    use_case.config = PricePollingConfig()
    use_case.subscription_repository = Mock()
    use_case.subscription_repository.list_active_asset_codes.return_value = []
    return use_case


def _assert_scope_unavailable(scope: Mapping[str, object]) -> None:
    """Assert that an unresolved monitor denominator stays explicitly unknown."""

    assert scope["prices"] == []
    assert scope["scope"] == "all_monitored_assets"
    assert scope["scope_available"] is False
    assert scope["requested"] is None
    assert scope["qualified"] is None
    assert scope["unavailable"] is None
    assert scope["outcome"] == "blocked"
    assert scope["is_reliable"] is False
    assert scope["is_stale"] is None
    assert scope["must_not_use_for_decision"] is True
    assert scope["blocked_reason"] == "monitored_price_scope_unavailable"


def _view_response(mocker, use_case: PricePollingUseCase, asset_code: str):
    """Exercise the real single-asset interface around the composed use case."""

    from apps.realtime.interface.views import SingleAssetPriceView

    mocker.patch("apps.realtime.interface.views.PricePollingUseCase", return_value=use_case)
    request = RequestFactory().get(f"/api/realtime/prices/{asset_code}/")
    return SingleAssetPriceView.as_view()(request, asset_code=asset_code)


def test_cached_published_quote_is_rechecked_before_single_asset_api(
    mocker, isolated_realtime_cache
):
    observed_at = datetime.now(UTC).replace(microsecond=0)
    current_payload = _quote_payload(observed_at=observed_at)
    quote_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=current_payload,
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )

    price = DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE)
    assert price is not None
    assert price.change_pct is None
    assert price.cache_source_kind == "data_center_publication"
    assert price.publication_id == "quote-pub-1"
    repository = RedisRealtimePriceRepository()
    repository.save_price(price)
    use_case = _use_case(repository)

    cached_response = _view_response(mocker, use_case, _ASSET_CODE)
    assert cached_response.status_code == 200
    cached_body = loads(cached_response.content)
    assert cached_body["timestamp"] == observed_at.isoformat()
    assert cached_body["freshness_status"] == "fresh"
    assert cached_body["must_not_use_for_decision"] is False
    assert quote_query.call_count == 2

    quote_query.return_value = _blocked_quote_payload()
    blocked_response = _view_response(mocker, use_case, _ASSET_CODE)
    assert blocked_response.status_code == 404
    assert quote_query.call_count == 3


@pytest.mark.parametrize(
    "invalid_price",
    [float("nan"), float("inf"), 10**400],
    ids=["nan", "infinity", "oversized-integer"],
)
def test_published_quote_rejects_non_finite_or_overflowing_numeric_payload(
    mocker,
    isolated_realtime_cache,
    invalid_price: object,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_quote_payload(observed_at=observed_at, price=invalid_price),
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )

    assert DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE) is None


def test_overflowing_quote_uses_qualified_daily_bar_fallback(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_quote_payload(
            observed_at=datetime(2026, 10, 23, 9, 30, tzinfo=UTC),
            price=10**400,
        ),
    )
    bar_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value={
            "rows": [
                {
                    "asset_code": _ASSET_CODE,
                    "timestamp": "2026-10-23",
                    "close": 9.87,
                    "volume": 500,
                    "source": "published_daily_bar",
                }
            ],
            "publication_id": "bar-pub-1",
            "dataset_key": _BAR_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        },
    )

    price = DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE)

    assert price is not None
    assert price.price == Decimal("9.87")
    assert price.cache_source_kind == "data_center_publication"
    assert price.publication_id == "bar-pub-1"
    assert price.publication_dataset_key == _BAR_DATASET
    assert price.timestamp.date().isoformat() == "2026-10-23"
    bar_query.assert_called_once_with(
        _ASSET_CODE,
        publication_key=_PUBLICATION_KEY,
        limit=1,
    )


@pytest.mark.parametrize(
    "current_state",
    [
        "replacement",
        "missing_identity",
        "unknown_eligibility",
        "member_blocked",
        "query_error",
    ],
)
def test_old_published_cache_fails_closed_when_current_identity_is_unprovable(
    mocker,
    isolated_realtime_cache,
    current_state: str,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    original_payload = _quote_payload(observed_at=observed_at)
    quote_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=original_payload,
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )
    original = DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE)
    assert original is not None
    repository = RedisRealtimePriceRepository()
    repository.save_price(original)

    if current_state == "replacement":
        quote_query.return_value = _quote_payload(
            publication_id="quote-pub-2",
            observed_at=observed_at,
            price=12.34,
        )
    elif current_state == "missing_identity":
        quote_query.return_value = {
            **original_payload,
            "publication_id": None,
        }
    elif current_state == "unknown_eligibility":
        quote_query.return_value = {
            **original_payload,
            "must_not_use_for_decision": None,
        }
    elif current_state == "member_blocked":
        rows = original_payload["rows"]
        assert isinstance(rows, list)
        row = rows[0]
        assert isinstance(row, dict)
        quote_query.return_value = {
            **original_payload,
            "rows": [
                {
                    **row,
                    "must_not_use_for_decision": True,
                    "blocked_reason": "member_not_eligible",
                }
            ],
        }
    else:
        quote_query.side_effect = RuntimeError("publication read unavailable")

    response = _view_response(mocker, _use_case(repository), _ASSET_CODE)
    assert response.status_code == 404
    assert loads(response.content)["success"] is False


def test_legacy_cache_without_publication_identity_is_not_assumed_eligible(
    isolated_realtime_cache,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    legacy = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=observed_at,
        source="vendor-quote",
    )
    cache.set(
        f"{RedisRealtimePriceRepository.CACHE_KEY_PREFIX}:{_ASSET_CODE}",
        legacy.to_dict(),
        timeout=300,
    )
    assert RedisRealtimePriceRepository().get_latest_price(_ASSET_CODE) is None


def test_external_adapter_marks_cache_provenance_explicitly() -> None:
    provider = AKSharePriceDataProvider.__new__(AKSharePriceDataProvider)
    price = provider._build_price_from_quote_snapshot(
        _ASSET_CODE,
        SimpleNamespace(
            price=Decimal("12.34"),
            volume=1000,
            observed_at=datetime.now(UTC),
            fetched_at=datetime.now(UTC),
            source="eastmoney-provider",
        ),
    )

    assert price is not None
    assert price.cache_source_kind == "external_provider"
    assert price.publication_id is None


def test_published_quote_member_for_another_asset_is_not_relabelled(mocker) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_quote_payload(
            asset_code="600000.SH",
            observed_at=observed_at,
        ),
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )

    assert DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE) is None


def test_published_bar_member_for_another_asset_is_not_relabelled(mocker) -> None:
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_blocked_quote_payload(),
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value={
            "rows": [
                {
                    "asset_code": "600000.SH",
                    "bar_date": date.today().isoformat(),
                    "close": 12.34,
                    "volume": 1000,
                    "source": "vendor-bar",
                }
            ],
            "publication_id": "bar-pub-1",
            "dataset_key": _BAR_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        },
    )

    assert DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE) is None


def test_external_provider_cache_remains_available_without_data_center_recheck(
    mocker,
    isolated_realtime_cache,
) -> None:
    external = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=datetime.now(UTC).replace(microsecond=0),
        source="akshare-provider",
        cache_source_kind="external_provider",
    )
    repository = RedisRealtimePriceRepository()
    repository.save_price(external)
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        side_effect=AssertionError("independent provider cache has no Data Center gate"),
    )

    assert repository.get_latest_price(_ASSET_CODE) == external


def test_current_publication_filter_is_per_asset(mocker, isolated_realtime_cache) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0)
    good_code = "000001.SZ"
    blocked_code = "600000.SH"
    repository = RedisRealtimePriceRepository()
    repository.save_prices_batch(
        [
            RealtimePrice(
                asset_code=code,
                asset_type=AssetType.EQUITY,
                price=Decimal("12.34"),
                change=None,
                change_pct=None,
                volume=1000,
                timestamp=observed_at,
                source="vendor-quote",
                fetched_at=observed_at + timedelta(seconds=1),
                cache_source_kind="data_center_publication",
                publication_id="pub-shared",
                publication_dataset_key=_QUOTE_DATASET,
                publication_key=_PUBLICATION_KEY,
            )
            for code in (good_code, blocked_code)
        ]
    )

    def query_current(asset_codes: list[str], *, publication_key: str) -> dict[str, object]:
        assert publication_key == _PUBLICATION_KEY
        assert asset_codes == [good_code, blocked_code]
        safe_row = _quote_payload(
            publication_id="pub-shared",
            asset_code=good_code,
            observed_at=observed_at,
        )["rows"][0]
        blocked_row = _quote_payload(
            publication_id="pub-shared",
            asset_code=blocked_code,
            observed_at=observed_at,
        )["rows"][0]
        assert isinstance(safe_row, dict)
        assert isinstance(blocked_row, dict)
        return {
            "rows": [
                safe_row,
                {
                    **blocked_row,
                    "must_not_use_for_decision": True,
                    "blocked_reason": "member_not_eligible",
                },
            ],
            "publication_id": "pub-shared",
            "dataset_key": _QUOTE_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        }

    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        side_effect=query_current,
    )

    assert [
        price.asset_code for price in repository.get_latest_prices([good_code, blocked_code])
    ] == [good_code]


def test_cached_monitored_prices_revalidates_publication_before_top_movers_payload(
    mocker,
    isolated_realtime_cache,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    good_code = "000001.SZ"
    blocked_code = "600000.SH"
    repository = RedisRealtimePriceRepository()
    repository.save_prices_batch(
        [
            RealtimePrice(
                asset_code=code,
                asset_type=AssetType.EQUITY,
                price=Decimal("12.34"),
                change=None,
                change_pct=None,
                volume=1000,
                timestamp=observed_at,
                source="vendor-quote",
                fetched_at=observed_at + timedelta(seconds=1),
                cache_source_kind="data_center_publication",
                publication_id="pub-shared",
                publication_dataset_key=_QUOTE_DATASET,
                publication_key=_PUBLICATION_KEY,
            )
            for code in (good_code, blocked_code)
        ]
    )
    good_row = {
        "asset_code": good_code,
        "snapshot_at": observed_at.isoformat(),
        "fetched_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "current_price": 12.34,
        "volume": 1000,
        "source": "vendor-quote",
    }
    blocked_row = {
        **good_row,
        "asset_code": blocked_code,
        "must_not_use_for_decision": True,
        "blocked_reason": "member_not_eligible",
    }
    quote_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value={
            "rows": [good_row, blocked_row],
            "publication_id": "pub-shared",
            "dataset_key": _QUOTE_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        side_effect=AssertionError("quote cache must not query the price-bar port"),
    )

    use_case = _use_case(repository)
    use_case.watchlist_provider = Mock()
    use_case.watchlist_provider.get_all_monitored_assets.return_value = [
        blocked_code,
        good_code,
    ]

    monitored = use_case.get_cached_monitored_price_scope()

    assert [item["asset_code"] for item in monitored["prices"]] == [good_code]
    assert monitored["prices"][0]["timestamp"] == observed_at.isoformat()
    assert monitored["scope"] == "all_monitored_assets"
    assert monitored["requested"] == 2
    assert monitored["qualified"] == 1
    assert monitored["unavailable"] == 1
    assert monitored["outcome"] == "partial"
    assert monitored["is_reliable"] is False
    assert monitored["is_stale"] is None
    assert monitored["must_not_use_for_decision"] is True
    assert monitored["blocked_reason"] == "monitored_cached_prices_incomplete"
    quote_query.assert_called_once_with(
        [good_code, blocked_code],
        publication_key=_PUBLICATION_KEY,
    )


def test_active_subscription_only_asset_remains_in_cached_scope_denominator(
    mocker,
    isolated_realtime_cache,
) -> None:
    observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    first_watchlist_code = "000001.SZ"
    second_watchlist_code = "000002.SZ"
    subscription_only_code = "600000.SH"
    repository = RedisRealtimePriceRepository()
    repository.save_prices_batch(
        [
            RealtimePrice(
                asset_code=code,
                asset_type=AssetType.EQUITY,
                price=Decimal("12.34"),
                change=None,
                change_pct=None,
                volume=1000,
                timestamp=observed_at,
                source="vendor-quote",
                fetched_at=observed_at + timedelta(seconds=1),
                cache_source_kind="data_center_publication",
                publication_id="pub-shared",
                publication_dataset_key=_QUOTE_DATASET,
                publication_key=_PUBLICATION_KEY,
            )
            for code in (first_watchlist_code, second_watchlist_code)
        ]
    )
    quote_rows = [
        _quote_payload(asset_code=code, observed_at=observed_at)["rows"][0]
        for code in (first_watchlist_code, second_watchlist_code)
    ]
    quote_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value={
            "rows": quote_rows,
            "publication_id": "pub-shared",
            "dataset_key": _QUOTE_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        side_effect=AssertionError("quote cache must not query the price-bar port"),
    )
    use_case = _use_case(repository)
    use_case.watchlist_provider = Mock()
    use_case.watchlist_provider.get_all_monitored_assets.return_value = [
        second_watchlist_code,
        first_watchlist_code,
    ]
    use_case.subscription_repository.list_active_asset_codes.return_value = [
        first_watchlist_code,
        subscription_only_code,
    ]

    monitored = use_case.get_cached_monitored_price_scope()

    assert [item["asset_code"] for item in monitored["prices"]] == [
        first_watchlist_code,
        second_watchlist_code,
    ]
    assert monitored["prices"][0]["timestamp"] == observed_at.isoformat()
    assert monitored["scope"] == "all_monitored_assets"
    assert monitored["requested"] == 3
    assert monitored["qualified"] == 2
    assert monitored["unavailable"] == 1
    assert monitored["outcome"] == "partial"
    assert monitored["is_reliable"] is False
    assert monitored["is_stale"] is None
    assert monitored["must_not_use_for_decision"] is True
    assert monitored["blocked_reason"] == "monitored_cached_prices_incomplete"
    quote_query.assert_called_once_with(
        [first_watchlist_code, second_watchlist_code],
        publication_key=_PUBLICATION_KEY,
    )


def test_database_watchlist_provider_union_reaches_top_movers_denominator(
    mocker,
    isolated_realtime_cache,
) -> None:
    from apps.realtime.application.query_services import get_cached_top_movers_result

    held_only_code = "000001.SZ"
    held_and_watchlist_code = "600000.SH"
    watchlist_only_code = "000002.SZ"
    subscription_only_code = "300001.SZ"
    held_query = mocker.patch(
        "apps.realtime.infrastructure.repositories.list_held_simulated_asset_codes",
        return_value=[held_only_code, held_and_watchlist_code],
    )
    watchlist_query = mocker.patch(
        "apps.realtime.infrastructure.repositories.list_active_watchlist_asset_codes",
        return_value=[held_and_watchlist_code, watchlist_only_code],
    )

    observed_at = datetime.now(UTC).replace(microsecond=0)
    change_by_code = {
        held_only_code: "1.0",
        held_and_watchlist_code: "2.0",
        watchlist_only_code: "4.0",
        subscription_only_code: "3.0",
    }
    repository = RedisRealtimePriceRepository()
    repository.save_prices_batch(
        [
            RealtimePrice(
                asset_code=asset_code,
                asset_type=AssetType.EQUITY,
                price=Decimal("12.34"),
                change=None,
                change_pct=Decimal(change_pct),
                volume=1000,
                timestamp=observed_at,
                source="isolated-test-provider",
                cache_source_kind="external_provider",
            )
            for asset_code, change_pct in change_by_code.items()
        ]
    )
    use_case = _use_case(repository)
    use_case.watchlist_provider = DatabaseWatchlistProvider()
    use_case.subscription_repository.list_active_asset_codes.return_value = [
        watchlist_only_code,
        subscription_only_code,
    ]
    top_movers_factory = mocker.patch(
        "apps.realtime.application.query_services.PricePollingUseCase",
        return_value=use_case,
    )

    result = get_cached_top_movers_result(direction="up", limit=1)

    held_query.assert_called_once_with()
    watchlist_query.assert_called_once_with()
    use_case.subscription_repository.list_active_asset_codes.assert_called_once_with()
    top_movers_factory.assert_called_once_with()
    assert result["requested"] == 4
    assert result["qualified"] == 4
    assert result["unavailable"] == 0
    assert result["rankable"] == 4
    assert result["unrankable"] == 0
    assert result["outcome"] == "success"
    assert result["count"] == 1
    assert [item["asset_code"] for item in result["results"]] == [watchlist_only_code]


def test_active_subscription_scope_failure_is_not_reported_as_complete(
    mocker,
    isolated_realtime_cache,
) -> None:
    use_case = _use_case(RedisRealtimePriceRepository())
    use_case.watchlist_provider = Mock()
    use_case.watchlist_provider.get_all_monitored_assets.return_value = ["000001.SZ"]
    use_case.subscription_repository.list_active_asset_codes.side_effect = RuntimeError(
        "subscription scope unavailable"
    )

    cache_read = mocker.patch.object(use_case.price_repository, "get_latest_prices")

    scope = use_case.get_cached_monitored_price_scope()

    _assert_scope_unavailable(scope)
    cache_read.assert_not_called()


def test_watchlist_query_failure_does_not_publish_held_only_scope_as_complete(
    mocker,
    isolated_realtime_cache,
) -> None:
    held_code = "000001.SZ"
    repository = RedisRealtimePriceRepository()
    repository.save_price(
        RealtimePrice(
            asset_code=held_code,
            asset_type=AssetType.EQUITY,
            price=Decimal("12.34"),
            change=None,
            change_pct=None,
            volume=1000,
            timestamp=datetime.now(UTC).replace(microsecond=0),
            source="independent-provider",
            cache_source_kind="external_provider",
        )
    )
    mocker.patch(
        "apps.realtime.infrastructure.repositories.list_held_simulated_asset_codes",
        return_value=[held_code],
    )
    watchlist_query = mocker.patch(
        "apps.realtime.infrastructure.repositories.list_active_watchlist_asset_codes",
        side_effect=RuntimeError("watchlist query unavailable"),
    )
    use_case = _use_case(repository)
    use_case.watchlist_provider = DatabaseWatchlistProvider()
    cache_read = mocker.patch.object(repository, "get_latest_prices")

    scope = use_case.get_cached_monitored_price_scope()

    _assert_scope_unavailable(scope)
    watchlist_query.assert_called_once_with()
    cache_read.assert_not_called()


def test_held_asset_scope_failure_blocks_without_reading_cached_prices(
    mocker,
    isolated_realtime_cache,
) -> None:
    held_query = mocker.patch(
        "apps.realtime.infrastructure.repositories.list_held_simulated_asset_codes",
        side_effect=RuntimeError("held asset query unavailable"),
    )
    use_case = _use_case(RedisRealtimePriceRepository())
    use_case.watchlist_provider = DatabaseWatchlistProvider()
    cache_read = mocker.patch.object(use_case.price_repository, "get_latest_prices")

    scope = use_case.get_cached_monitored_price_scope()

    _assert_scope_unavailable(scope)
    held_query.assert_called_once_with()
    cache_read.assert_not_called()


def test_top_movers_limit_does_not_shrink_monitored_scope_denominator(mocker) -> None:
    from apps.realtime.application.query_services import get_cached_top_movers_result

    scope = {
        "prices": [
            {"asset_code": "000001.SZ", "change_pct": "3.0"},
            {"asset_code": "600000.SH", "change_pct": "2.0"},
            {"asset_code": "000002.SZ", "change_pct": "1.0"},
        ],
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": 3,
        "qualified": 3,
        "unavailable": 0,
        "outcome": "success",
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
    use_case = mocker.patch(
        "apps.realtime.application.query_services.PricePollingUseCase"
    ).return_value
    use_case.get_cached_monitored_price_scope.return_value = scope

    result = get_cached_top_movers_result(direction="up", limit=1)

    assert result["count"] == 1
    assert [item["asset_code"] for item in result["results"]] == ["000001.SZ"]
    assert result["requested"] == 3
    assert result["qualified"] == 3
    assert result["unavailable"] == 0
    assert result["rankable"] == 3
    assert result["unrankable"] == 0
    assert result["scope_available"] is True
    assert result["outcome"] == "success"
    assert result["is_reliable"] is True

    partial_scope = {
        **scope,
        "prices": scope["prices"][:1],
        "requested": 2,
        "qualified": 1,
        "unavailable": 1,
        "outcome": "partial",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_cached_prices_incomplete",
    }
    use_case.get_cached_monitored_price_scope.return_value = partial_scope
    partial_result = get_cached_top_movers_result(direction="up", limit=1)

    assert partial_result["count"] == 1
    assert partial_result["requested"] == 2
    assert partial_result["qualified"] == 1
    assert partial_result["unavailable"] == 1
    assert partial_result["rankable"] == 1
    assert partial_result["unrankable"] == 0
    assert partial_result["scope_available"] is True
    assert partial_result["outcome"] == "partial"
    assert partial_result["is_reliable"] is False
    assert partial_result["is_stale"] is None
    assert partial_result["must_not_use_for_decision"] is True
    assert partial_result["blocked_reason"] == "monitored_cached_prices_incomplete"

    unavailable_scope = {
        **scope,
        "prices": [],
        "scope_available": False,
        "requested": None,
        "qualified": None,
        "unavailable": None,
        "outcome": "blocked",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_price_scope_unavailable",
    }
    use_case.get_cached_monitored_price_scope.return_value = unavailable_scope
    unavailable_result = get_cached_top_movers_result(direction="up", limit=1)

    assert unavailable_result["results"] == []
    assert unavailable_result["count"] == 0
    assert unavailable_result["scope_available"] is False
    assert unavailable_result["requested"] is None
    assert unavailable_result["qualified"] is None
    assert unavailable_result["unavailable"] is None
    assert unavailable_result["rankable"] is None
    assert unavailable_result["unrankable"] is None
    assert unavailable_result["outcome"] == "blocked"
    assert unavailable_result["is_reliable"] is False
    assert unavailable_result["is_stale"] is None
    assert unavailable_result["must_not_use_for_decision"] is True
    assert unavailable_result["blocked_reason"] == "monitored_price_scope_unavailable"
    assert use_case.get_cached_monitored_price_scope.call_count == 3


@pytest.mark.parametrize(
    ("direction", "expected_codes"),
    [
        ("up", ["positive", "zero"]),
        ("down", ["negative", "zero"]),
    ],
)
def test_top_movers_counts_only_finite_change_percent_as_rankable(
    mocker,
    direction: str,
    expected_codes: list[str],
) -> None:
    from apps.realtime.application.query_services import get_cached_top_movers_result

    prices = [
        {"asset_code": "positive", "change_pct": "2.5"},
        {"asset_code": "zero", "change_pct": 0.0},
        {"asset_code": "negative", "change_pct": "-0.7"},
        {"asset_code": "missing", "change_pct": None},
        {"asset_code": "nan", "change_pct": "NaN"},
        {"asset_code": "infinite", "change_pct": float("inf")},
        {"asset_code": "overflow", "change_pct": 10**400},
        {"asset_code": "boolean", "change_pct": True},
    ]
    scope = {
        "prices": prices,
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": len(prices),
        "qualified": len(prices),
        "unavailable": 0,
        "outcome": "success",
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
    use_case = mocker.patch(
        "apps.realtime.application.query_services.PricePollingUseCase"
    ).return_value
    use_case.get_cached_monitored_price_scope.return_value = scope

    result = get_cached_top_movers_result(direction=direction, limit=2)

    assert [item["asset_code"] for item in result["results"]] == expected_codes
    assert result["count"] == 2
    assert result["requested"] == len(prices)
    assert result["qualified"] == len(prices)
    assert result["unavailable"] == 0
    assert result["rankable"] == 3
    assert result["unrankable"] == 5
    assert result["outcome"] == "partial"
    assert result["blocked_reason"] == "monitored_top_movers_change_pct_unavailable"
    assert result["is_stale"] is False
    assert result["must_not_use_for_decision"] is True


def test_top_movers_with_no_rankable_change_percent_blocks_without_staling_prices(mocker) -> None:
    from apps.realtime.application.query_services import get_cached_top_movers_result

    prices = [
        {"asset_code": "missing", "change_pct": None},
        {"asset_code": "nan", "change_pct": float("nan")},
        {"asset_code": "overflow", "change_pct": 10**400},
        {"asset_code": "boolean", "change_pct": False},
    ]
    scope = {
        "prices": prices,
        "scope": "all_monitored_assets",
        "scope_available": True,
        "requested": len(prices),
        "qualified": len(prices),
        "unavailable": 0,
        "outcome": "success",
        "is_reliable": True,
        "is_stale": False,
        "must_not_use_for_decision": False,
        "blocked_reason": "",
    }
    use_case = mocker.patch(
        "apps.realtime.application.query_services.PricePollingUseCase"
    ).return_value
    use_case.get_cached_monitored_price_scope.return_value = scope

    result = get_cached_top_movers_result(direction="up", limit=10)

    assert result["results"] == []
    assert result["requested"] == len(prices)
    assert result["qualified"] == len(prices)
    assert result["unavailable"] == 0
    assert result["rankable"] == 0
    assert result["unrankable"] == len(prices)
    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "monitored_top_movers_change_pct_unavailable"
    assert result["is_stale"] is False
    assert result["must_not_use_for_decision"] is True


@pytest.mark.parametrize(
    ("scope_available", "requested", "qualified", "unavailable", "prices"),
    [
        (True, 2, 1, 1, [{"asset_code": "A", "change_pct": 1.0}]),
        (False, None, None, None, []),
    ],
    ids=["partial", "unknown-scope"],
)
def test_legacy_top_movers_list_rejects_partial_or_unknown_scope(
    mocker,
    scope_available: bool,
    requested: int | None,
    qualified: int | None,
    unavailable: int | None,
    prices: list[dict[str, object]],
) -> None:
    from apps.realtime.application.query_services import list_cached_top_movers_payloads
    from core.exceptions import DataFetchError

    scope = {
        "prices": prices,
        "scope": "all_monitored_assets",
        "scope_available": scope_available,
        "requested": requested,
        "qualified": qualified,
        "unavailable": unavailable,
        "outcome": "partial" if scope_available else "blocked",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": (
            "monitored_cached_prices_incomplete"
            if scope_available
            else "monitored_price_scope_unavailable"
        ),
    }
    mocker.patch(
        "apps.realtime.application.query_services.PricePollingUseCase"
    ).return_value.get_cached_monitored_price_scope.return_value = scope

    with pytest.raises(DataFetchError) as raised:
        list_cached_top_movers_payloads()

    assert raised.value.code == "MONITORED_TOP_MOVERS_NOT_DECISION_USABLE"
    assert raised.value.details["outcome"] == scope["outcome"]


def test_cached_published_bar_requires_same_current_bar_publication(
    mocker,
    isolated_realtime_cache,
) -> None:
    bar_date = date.today()
    safe_bar = {
        "rows": [
            {
                "asset_code": _ASSET_CODE,
                "bar_date": bar_date.isoformat(),
                "close": 12.34,
                "volume": 1000,
                "source": "vendor-bar",
            }
        ],
        "publication_id": "bar-pub-1",
        "dataset_key": _BAR_DATASET,
        "publication_key": _PUBLICATION_KEY,
        "must_not_use_for_decision": False,
    }
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_blocked_quote_payload(),
    )
    bar_query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=safe_bar,
    )
    price = DataCenterPriceDataProvider().get_realtime_price(_ASSET_CODE)
    assert price is not None
    assert price.publication_dataset_key == _BAR_DATASET
    repository = RedisRealtimePriceRepository()
    repository.save_price(price)

    cached = repository.get_latest_price(_ASSET_CODE)
    assert cached is not None
    assert cached.timestamp == price.timestamp
    bar_query.return_value = {
        **safe_bar,
        "publication_id": "bar-pub-2",
    }
    assert repository.get_latest_price(_ASSET_CODE) is None
