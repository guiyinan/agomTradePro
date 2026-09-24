"""Later ingestion must preserve the exact rows referenced by a publication."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.domain.entities import PriceBar, QuoteSnapshot, ValuationFact
from apps.data_center.infrastructure.models import (
    PriceBarModel,
    QuoteSnapshotModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.publication_fact_evidence import canonical_fact_content_hash
from apps.data_center.infrastructure.publication_models import PublicationMemberModel
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from core.exceptions import DataFetchError

pytestmark = pytest.mark.django_db


def _pin(row, dataset):
    PublicationMemberModel.objects.create(
        publication_id=uuid4(),
        dataset_key=dataset,
        natural_key=str(row.pk),
        source=row.source,
        source_record_id="retained-source-row",
        fact_table=row._meta.db_table,
        fact_pk=str(row.pk),
        fact_content_hash=canonical_fact_content_hash(row),
    )


def test_refreshing_published_quote_keeps_frozen_row_and_selects_new_revision():
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    repo = QuoteSnapshotRepository()
    first = QuoteSnapshot("000001.SZ", observed, 10.5, "provider", fetched_at=observed)
    repo.bulk_upsert([first])
    old = QuoteSnapshotModel.objects.get(asset_code=first.asset_code)
    _pin(old, "equity.quote.snapshot")
    digest = canonical_fact_content_hash(old)
    second = replace(first, current_price=10.75, fetched_at=observed + timedelta(hours=1))
    assert repo.bulk_upsert([second]) == 1
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == digest
    assert QuoteSnapshotModel.objects.filter(asset_code=first.asset_code).count() == 2
    assert repo.get_latest(first.asset_code).current_price == 10.75
    assert len(repo.get_series(first.asset_code)) == 1
    assert repo.get_latest(first.asset_code, fact_pks=[str(old.pk)]).current_price == 10.5
    assert repo.list_publication_candidates([second])[0].fact_pk != str(old.pk)
    assert repo.list_current_publication_candidates((first.asset_code,))[0].revision_number == 2


def test_refetching_published_valuation_does_not_rewrite_knowledge_time():
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    repo = ValuationFactRepository()
    first = ValuationFact(
        "000001.SZ",
        observed.date(),
        pe_ttm=12.5,
        source="provider",
        observed_at=observed,
        fetched_at=observed,
        available_at=observed,
    )
    repo.bulk_upsert([first])
    old = ValuationFactModel.objects.get(asset_code=first.asset_code)
    _pin(old, "equity.valuation.fact")
    digest = canonical_fact_content_hash(old)
    later = observed + timedelta(hours=1)
    second = replace(first, pe_ttm=13.5, fetched_at=later, available_at=later)
    assert repo.bulk_upsert([second]) == 1
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == digest
    assert old.available_at == observed
    assert repo.get_latest(first.asset_code).available_at == later
    assert len(repo.get_series(first.asset_code)) == 1
    assert len(repo.list_by_date(first.val_date)) == 1
    assert repo.get_series(first.asset_code, fact_pks=[str(old.pk)])[0].pe_ttm == 12.5
    assert repo.list_publication_candidates([second])[0].fact_pk != str(old.pk)
    assert repo.list_current_publication_candidates((first.asset_code,))[0].revision_number == 2
    # Exact replay of an unmodified latest revision must not create unbounded duplicates.
    repo.bulk_upsert([second])
    assert ValuationFactModel.objects.filter(asset_code=first.asset_code).count() == 2


def test_duplicate_batch_rolls_back_without_changing_frozen_or_unpublished_rows():
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    repo = QuoteSnapshotRepository()
    first = QuoteSnapshot("000001.SZ", observed, 10.5, "provider", fetched_at=observed)
    repo.bulk_upsert([first])
    old = QuoteSnapshotModel.objects.get(asset_code=first.asset_code)
    _pin(old, "equity.quote.snapshot")
    digest = canonical_fact_content_hash(old)
    changed = replace(first, current_price=12)
    with pytest.raises(DataFetchError, match="Duplicate fact identity"):
        repo.bulk_upsert([changed, changed])
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == digest
    assert QuoteSnapshotModel.objects.count() == 1


def test_exact_replay_of_frozen_quote_does_not_create_new_revision():
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    repo = QuoteSnapshotRepository()
    first = QuoteSnapshot("000001.SZ", observed, 10.3, "provider", fetched_at=observed)
    repo.bulk_upsert([first])
    old = QuoteSnapshotModel.objects.get(asset_code=first.asset_code)
    _pin(old, "equity.quote.snapshot")
    repo.bulk_upsert([first])
    assert QuoteSnapshotModel.objects.count() == 1


def test_correcting_published_daily_bar_preserves_snapshot_and_latest_history():
    repo = PriceBarRepository()
    first = PriceBar("000001.SZ", datetime(2026, 9, 24).date(), 10, 12, 9, 11, source="provider")
    assert repo.bulk_upsert([first]) == 1
    old = PriceBarModel.objects.get()
    _pin(old, "equity.price.bar")
    digest = canonical_fact_content_hash(old)
    corrected = replace(first, close=11.5)
    assert repo.bulk_upsert([corrected]) == 1
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == digest
    assert repo.get_latest(first.asset_code).close == 11.5
    assert repo.get_latest(first.asset_code, fact_pks=[str(old.pk)]).close == 11
    assert len(repo.get_bars(first.asset_code)) == 1
    assert repo.list_publication_candidates([corrected])[0].revision_number == 2
    assert repo.list_current_publication_candidates((first.asset_code,))[0].revision_number == 2
    assert repo.bulk_upsert([corrected]) == 1
    assert PriceBarModel.objects.count() == 2


def test_market_sized_unpublished_refetch_uses_bounded_insert_upserts():
    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    facts = [
        ValuationFact(
            f"{index:06d}.SZ",
            observed.date(),
            pe_ttm=12.5,
            source="provider",
            observed_at=observed,
            fetched_at=observed,
            available_at=observed,
        )
        for index in range(5557)
    ]
    repo = ValuationFactRepository()
    assert repo.bulk_upsert(facts) == 5557
    changed = [replace(fact, pe_ttm=13.5) for fact in facts]
    with CaptureQueriesContext(connection) as captured:
        assert repo.bulk_upsert(changed) == 5557
    assert ValuationFactModel.objects.count() == 5557
    assert ValuationFactModel.objects.filter(pe_ttm=13.5).count() == 5557
    assert len(captured) < 350
    assert not any(query["sql"].lstrip().startswith("UPDATE ") for query in captured)
