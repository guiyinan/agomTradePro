"""Source observation evidence must survive valuation persistence unchanged."""

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.domain.entities import ValuationFact
from apps.data_center.infrastructure.models import ValuationFactModel
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository


@pytest.mark.django_db
def test_valuation_insert_preserves_distinct_source_fetch_and_availability_times() -> None:
    observed = datetime(2026, 8, 28, 7, 14, 36, tzinfo=UTC)
    fetched = observed + timedelta(seconds=12)
    available = observed - timedelta(hours=1)
    fact = ValuationFact(
        asset_code="000001.SZ",
        val_date=date(2026, 8, 28),
        pe_ttm=12.5,
        source="akshare",
        observed_at=observed,
        fetched_at=fetched,
        available_at=available,
    )
    repository = ValuationFactRepository()

    assert repository.bulk_upsert([fact]) == 1
    stored = repository.get_latest(fact.asset_code)

    assert stored is not None
    assert stored.observed_at == observed
    assert stored.fetched_at == fetched
    assert stored.available_at == available
    assert stored.to_dict()["observed_at"] == observed.isoformat()
    references = repository.list_publication_candidates([stored])
    assert len(references) == 1
    assert references[0].observed_at == observed
    assert references[0].observed_at not in (fetched, available)


@pytest.mark.django_db
def test_same_day_valuation_refresh_updates_source_time_fetch_time_and_evidence_hash() -> None:
    first_observed = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)
    second_observed = first_observed + timedelta(hours=1)
    available = first_observed - timedelta(hours=1)
    repository = ValuationFactRepository()
    first = ValuationFact(
        asset_code="000001.SZ",
        val_date=date(2026, 8, 28),
        pe_ttm=12.5,
        source="akshare",
        observed_at=first_observed,
        fetched_at=first_observed + timedelta(seconds=5),
        available_at=available,
    )
    assert repository.bulk_upsert([first]) == 1
    before_reference = repository.list_publication_candidates([first])[0]
    original_pk = ValuationFactModel.objects.get(asset_code=first.asset_code).pk
    second = ValuationFact(
        asset_code=first.asset_code,
        val_date=first.val_date,
        pe_ttm=first.pe_ttm,
        source=first.source,
        observed_at=second_observed,
        fetched_at=second_observed + timedelta(seconds=7),
        available_at=available,
    )

    assert repository.bulk_upsert([second]) == 1
    stored = repository.get_latest(first.asset_code)
    after_reference = repository.list_publication_candidates([second])[0]

    assert stored is not None
    assert ValuationFactModel.objects.get(asset_code=first.asset_code).pk == original_pk
    assert stored.observed_at == second.observed_at
    assert stored.fetched_at == second.fetched_at
    assert stored.available_at == available
    assert after_reference.observed_at == second_observed
    assert after_reference.raw_payload_hash != before_reference.raw_payload_hash


@pytest.mark.django_db
def test_refreshed_valuation_does_not_reuse_previous_source_payload_evidence() -> None:
    observed = datetime(2026, 8, 28, 6, tzinfo=UTC)
    row = ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=observed.date(),
        source="akshare",
        pe_ttm=12.5,
        observed_at=observed,
        fetched_at=observed + timedelta(seconds=5),
        source_record_id="previous-provider-response",
        raw_payload_hash="a" * 64,
    )
    repository = ValuationFactRepository()
    previous = repository.get_latest(row.asset_code)
    assert previous is not None
    assert previous.source_record_id == row.source_record_id
    assert previous.raw_payload_hash == row.raw_payload_hash

    refreshed = ValuationFact(
        asset_code=row.asset_code,
        val_date=row.val_date,
        source=row.source,
        pe_ttm=13.5,
        observed_at=observed + timedelta(hours=1),
        fetched_at=observed + timedelta(hours=1, seconds=5),
    )
    assert repository.bulk_upsert([refreshed]) == 1
    row.refresh_from_db()
    assert row.raw_payload_hash == ""
    assert row.source_record_id == ""
    reference = repository.list_publication_candidates([refreshed])[0]
    assert reference.raw_payload_hash != "a" * 64
    assert reference.source_record_id != "previous-provider-response"


@pytest.mark.django_db
def test_legacy_valuation_does_not_invent_observation_from_date_or_availability() -> None:
    ValuationFactModel.objects.create(
        asset_code="000001.SZ",
        val_date=date(2026, 8, 28),
        source="akshare",
        pe_ttm=12.5,
        available_at=datetime(2026, 8, 28, 6, tzinfo=UTC),
    )
    repository = ValuationFactRepository()
    stored = repository.get_latest("000001.SZ")

    assert stored is not None
    assert stored.observed_at is None
    with pytest.raises(ValueError, match="observed_at"):
        repository.list_publication_candidates([stored])
    with pytest.raises(ValueError, match="observed_at"):
        repository.list_current_publication_candidates(("000001.SZ",))
