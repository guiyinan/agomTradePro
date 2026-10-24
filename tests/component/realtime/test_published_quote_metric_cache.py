"""Published quote metric cache identity and persistence checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import override_settings

from apps.realtime.domain.entities import AssetType, RealtimePrice
from apps.realtime.infrastructure.repositories import RedisRealtimePriceRepository

_ASSET_CODE = "000001.SZ"
_PUBLICATION_KEY = "current"
_QUOTE_DATASET = "equity.quote.snapshot"


@pytest.fixture
def isolated_realtime_cache():
    """Use a real Django cache backend isolated from other test cache keys."""

    settings = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ash04-realtime-publication-cache-metric",
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


def test_cached_quote_change_pct_requires_matching_metric_and_contract_evidence() -> None:
    """A current price match cannot preserve a changed or unproven metric."""

    import hashlib
    import json

    from apps.data_center.domain.contracts import QuoteMetricSourceContract
    from apps.realtime.infrastructure.publication_price_cache import (
        _payload_row_matches_cached_price,
    )

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-quote",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-a",
    )
    evidence: dict[str, object] = {
        **source_contract.to_dict(),
        "source_contract_hash": source_contract.content_hash,
        "observed_at": observed_at.isoformat(),
        "source_value": "0",
        "dataset_contract_key": "equity.quote.snapshot",
        "dataset_contract_version": "2.0",
        "dataset_schema_version": "2.0",
        "metric_value": "0",
        "quote_source": "vendor-quote",
    }
    evidence_hash = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    price = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=Decimal("0"),
        volume=1000,
        timestamp=observed_at,
        source="vendor-quote",
        fetched_at=observed_at + timedelta(seconds=1),
        cache_source_kind="data_center_publication",
        publication_id="quote-pub-1",
        publication_dataset_key=_QUOTE_DATASET,
        publication_key=_PUBLICATION_KEY,
        change_pct_evidence_hash=evidence_hash,
    )
    row: dict[str, object] = {
        "asset_code": _ASSET_CODE,
        "snapshot_at": observed_at.isoformat(),
        "fetched_at": (observed_at + timedelta(seconds=1)).isoformat(),
        "current_price": 12.34,
        "change_pct": 0,
        "change_pct_source_contract": evidence,
        "contract_version": "2.0",
        "schema_version": "2.0",
        "volume": 1000,
        "source": "vendor-quote",
        "extra": {"actual_source": "vendor-quote"},
        "must_not_use_for_decision": False,
    }

    assert _payload_row_matches_cached_price(price, row) is True
    assert _payload_row_matches_cached_price(price, {**row, "change_pct": 0.01}) is False
    assert (
        _payload_row_matches_cached_price(
            price,
            {**row, "extra": {"actual_source": "other-provider"}},
        )
        is False
    )
    assert _payload_row_matches_cached_price(price, {**row, "extra": {"actual_source": 7}}) is False
    tampered_evidence = {**evidence, "action_basis": "basis-b"}
    assert (
        _payload_row_matches_cached_price(
            price,
            {**row, "change_pct_source_contract": tampered_evidence},
        )
        is False
    )
    assert (
        _payload_row_matches_cached_price(
            price,
            {key: value for key, value in row.items() if key != "change_pct_source_contract"},
        )
        is False
    )


def test_published_quote_metric_flows_through_cache_and_rejects_metric_revision(
    mocker,
    isolated_realtime_cache,
) -> None:
    """The cached metric stays usable only while the current published row agrees."""

    import hashlib
    import json

    from apps.data_center.domain.contracts import QuoteMetricSourceContract
    from apps.data_center.domain.entities import QuoteChangePctEvidence
    from apps.realtime.infrastructure.publication_price_cache import (
        published_data_center_price,
    )

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-quote",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-a",
    )

    def _row(metric: str) -> dict[str, object]:
        evidence = QuoteChangePctEvidence(
            metric_value=Decimal(metric),
            source_value=metric,
            dataset_contract_key="equity.quote.snapshot",
            dataset_contract_version="2.0",
            dataset_schema_version="2.0",
            source_contract=source_contract,
            source_contract_hash=source_contract.content_hash,
            observed_at=observed_at,
            quote_source="vendor-quote",
        ).to_dict()
        return {
            "asset_code": _ASSET_CODE,
            "snapshot_at": observed_at.isoformat(),
            "fetched_at": (observed_at + timedelta(seconds=1)).isoformat(),
            "current_price": 12.34,
            "change_pct": metric,
            "change_pct_source_contract": evidence,
            "contract_version": "2.0",
            "schema_version": "2.0",
            "volume": 1000,
            "source": "vendor-quote",
            "extra": {"actual_source": "vendor-quote"},
        }

    def _publication(metric: str) -> dict[str, object]:
        return {
            "rows": [_row(metric)],
            "publication_id": "quote-pub-1",
            "dataset_key": _QUOTE_DATASET,
            "publication_key": _PUBLICATION_KEY,
            "must_not_use_for_decision": False,
        }

    query = mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_publication("0"),
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )
    price = published_data_center_price(_ASSET_CODE, AssetType.EQUITY)

    assert price is not None
    assert price.change_pct == Decimal("0")
    assert (
        price.change_pct_evidence_hash
        == hashlib.sha256(
            json.dumps(
                _row("0")["change_pct_source_contract"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    repository = RedisRealtimePriceRepository()
    repository.save_price(price)
    current = repository.get_latest_price(_ASSET_CODE)
    assert current is not None
    assert current.change_pct == Decimal("0")

    query.return_value = _publication("1")

    assert repository.get_latest_price(_ASSET_CODE) is None


def test_cache_revalidation_keeps_object_identity_for_same_asset_code(mocker) -> None:
    """A valid quote cannot qualify same-code cache objects with other identities."""

    from dataclasses import replace

    from apps.realtime.infrastructure.publication_price_cache import (
        currently_qualified_cache_prices,
    )

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    current_payload = _quote_payload(observed_at=observed_at)
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=current_payload,
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )
    good_price = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=observed_at,
        source="vendor-quote",
        fetched_at=observed_at + timedelta(seconds=1),
        cache_source_kind="data_center_publication",
        publication_id="quote-pub-1",
        publication_dataset_key=_QUOTE_DATASET,
        publication_key=_PUBLICATION_KEY,
    )
    tampered_metric = replace(good_price, change_pct=Decimal("0"))
    tampered_price = replace(good_price, price=Decimal("12.35"))
    external_same_code = replace(
        good_price,
        cache_source_kind="external_provider",
        publication_id=None,
        publication_dataset_key=None,
        publication_key=None,
    )
    legacy_unknown_same_code = replace(
        good_price,
        cache_source_kind=None,
        publication_id=None,
        publication_dataset_key=None,
        publication_key=None,
    )

    accepted = currently_qualified_cache_prices(
        [
            good_price,
            tampered_metric,
            tampered_price,
            external_same_code,
            legacy_unknown_same_code,
        ]
    )

    assert accepted == [good_price, external_same_code]
    assert accepted[0] is good_price
    assert accepted[1] is external_same_code


def test_bulk_cache_reader_does_not_requalify_another_same_code_object(mocker) -> None:
    """The repository keeps object-level cache eligibility after its batch read."""

    from dataclasses import replace

    from apps.realtime.infrastructure.publication_price_cache import cache_payload

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    good_price = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=None,
        volume=1000,
        timestamp=observed_at,
        source="vendor-quote",
        fetched_at=observed_at + timedelta(seconds=1),
        cache_source_kind="data_center_publication",
        publication_id="quote-pub-1",
        publication_dataset_key=_QUOTE_DATASET,
        publication_key=_PUBLICATION_KEY,
    )
    mismatched_price = replace(good_price, price=Decimal("12.35"))
    mocker.patch(
        "apps.realtime.infrastructure.repositories.cache.get_many",
        return_value={
            f"{RedisRealtimePriceRepository.CACHE_KEY_PREFIX}:{_ASSET_CODE}": cache_payload(
                good_price
            ),
            f"{RedisRealtimePriceRepository.CACHE_KEY_PREFIX}:000001": cache_payload(
                mismatched_price
            ),
        },
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_quote_payloads",
        return_value=_quote_payload(observed_at=observed_at),
    )
    mocker.patch(
        "apps.realtime.infrastructure.publication_price_cache.get_published_price_bar_series",
        return_value=_blocked_quote_payload(),
    )

    results = RedisRealtimePriceRepository().get_latest_prices([_ASSET_CODE, "000001"])

    assert len(results) == 1
    assert results[0].price == Decimal("12.34")


def test_realtime_cache_roundtrip_preserves_exact_metric_and_contract_hash() -> None:
    """The Redis adapter keeps supported Decimal precision and evidence identity."""

    from apps.realtime.infrastructure.publication_price_cache import cache_payload

    metric = Decimal("1.234567891234")
    price = RealtimePrice(
        asset_code=_ASSET_CODE,
        asset_type=AssetType.EQUITY,
        price=Decimal("12.34"),
        change=None,
        change_pct=metric,
        volume=1000,
        timestamp=datetime(2026, 10, 23, 7, 30, tzinfo=UTC),
        source="vendor-quote",
        fetched_at=datetime(2026, 10, 23, 7, 30, 1, tzinfo=UTC),
        cache_source_kind="data_center_publication",
        publication_id="quote-pub-1",
        publication_dataset_key=_QUOTE_DATASET,
        publication_key=_PUBLICATION_KEY,
        change_pct_evidence_hash="a" * 64,
    )

    decoded = RedisRealtimePriceRepository()._dict_to_price(cache_payload(price))

    assert decoded.change_pct == metric
    assert decoded.change_pct_evidence_hash == price.change_pct_evidence_hash
