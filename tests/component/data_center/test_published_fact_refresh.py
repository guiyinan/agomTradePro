"""Later ingestion must preserve the exact rows referenced by a publication."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application import public_published_queries, query_services
from apps.data_center.application.publication_utils import publication_member_from_reference
from apps.data_center.domain.entities import PriceBar, QuoteSnapshot, ValuationFact
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.financial_fact_repository import FinancialFactRepository
from apps.data_center.infrastructure.models import (
    FinancialFactModel,
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


def _pin(row, dataset, *, observed_at=None, natural_key=None):
    publication_id = uuid4()
    PublicationMemberModel.objects.create(
        publication_id=publication_id,
        dataset_key=dataset,
        natural_key=natural_key or str(row.pk),
        source=row.source,
        source_record_id="retained-source-row",
        fact_table=row._meta.db_table,
        fact_pk=str(row.pk),
        fact_content_hash=canonical_fact_content_hash(row),
        observed_at=observed_at,
    )
    return str(publication_id)


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


def test_unpublished_quote_revision_is_visible_to_legacy_latest_but_not_current_publication_read(
    monkeypatch,
) -> None:
    """The raw latest port sees staging while the publication port stays member-bound."""

    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    repo = QuoteSnapshotRepository()
    first = QuoteSnapshot("000001.SZ", observed, 10.5, "provider", fetched_at=observed)
    repo.bulk_upsert([first])
    reference = repo.list_publication_candidates([first])[0]
    publication_id = str(uuid4())
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=publication_id,
        dataset_key="equity.quote.snapshot",
    )
    publications = CanonicalPublicationRepository()
    assert publications.add_member(member) == member

    unpublished_revision = replace(
        first,
        current_price=10.75,
        fetched_at=observed + timedelta(minutes=1),
    )
    assert repo.bulk_upsert([unpublished_revision]) == 1
    monkeypatch.setattr(
        query_services,
        "_publication_gate",
        lambda *_args, **_kwargs: {
            "dataset_key": "equity.quote.snapshot",
            "publication_id": publication_id,
            "publication_key": "current",
            "as_of": (observed + timedelta(hours=1)).isoformat(),
            "must_not_use_for_decision": False,
        },
    )
    monkeypatch.setattr(
        query_services,
        "get_canonical_publication_repository",
        lambda: publications,
    )
    monkeypatch.setattr(query_services, "get_quote_snapshot_repository", lambda: repo)

    legacy_latest = query_services.query_latest_quote_payloads([first.asset_code])
    published = query_services.query_published_quote_payloads([first.asset_code])

    assert [row["current_price"] for row in legacy_latest] == [10.75]
    assert [row["current_price"] for row in published["rows"]] == [10.5]
    unpublished_row = QuoteSnapshotModel._default_manager.get(revision_number=2)
    assert member.fact_pk != str(unpublished_row.pk)


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


def test_unpublished_valuation_and_financial_revisions_stay_outside_published_reads(
    monkeypatch,
) -> None:
    """Published decision reads resolve exact member PKs, never newer staged revisions."""

    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    asset_code = "000001.SZ"
    valuation_repository = ValuationFactRepository()
    valuation = ValuationFact(
        asset_code,
        observed.date(),
        pe_ttm=12.5,
        source="provider",
        observed_at=observed,
        fetched_at=observed,
        available_at=observed,
    )
    valuation_repository.bulk_upsert([valuation])
    old_valuation = ValuationFactModel.objects.get(asset_code=asset_code)
    valuation_publication_id = _pin(old_valuation, "equity.valuation.fact")
    valuation_repository.bulk_upsert(
        [replace(valuation, pe_ttm=99.0, fetched_at=observed + timedelta(minutes=1))]
    )

    old_financial = FinancialFactModel.objects.create(
        asset_code=asset_code,
        period_end=observed.date(),
        period_type="quarterly",
        metric_code="roe",
        value="0.2000",
        unit="ratio",
        source="provider",
        announced_at=observed,
        available_at=observed,
        revision_number=1,
    )
    financial_publication_id = _pin(old_financial, "equity.financial.fact")
    FinancialFactModel.objects.create(
        asset_code=asset_code,
        period_end=observed.date(),
        period_type="quarterly",
        metric_code="roe",
        value="0.9900",
        unit="ratio",
        source="provider",
        announced_at=observed,
        available_at=observed + timedelta(minutes=1),
        revision_number=2,
    )

    publication_ids = {
        "equity.valuation.fact": valuation_publication_id,
        "equity.financial.fact": financial_publication_id,
    }

    def _gate(dataset_key: str, *_args, **_kwargs) -> dict[str, object]:
        return {
            "dataset_key": dataset_key,
            "publication_id": publication_ids[dataset_key],
            "publication_key": "current",
            "as_of": (observed + timedelta(hours=1)).isoformat(),
            "must_not_use_for_decision": False,
        }

    publications = CanonicalPublicationRepository()
    monkeypatch.setattr(query_services, "_publication_gate", _gate)
    monkeypatch.setattr(
        query_services, "get_canonical_publication_repository", lambda: publications
    )
    monkeypatch.setattr(
        query_services, "get_valuation_fact_repository", lambda: valuation_repository
    )
    monkeypatch.setattr(
        query_services, "get_financial_fact_repository", lambda: FinancialFactRepository()
    )

    raw_valuation = query_services.query_valuation_facts(asset_code, as_of=observed.date())
    raw_financial = query_services.query_financial_facts(asset_code, limit=1)
    published_valuation = query_services.query_published_valuation_facts(
        asset_code, as_of=observed.date()
    )
    published_financial = query_services.query_published_financial_facts(
        asset_code, as_of=observed.date()
    )

    assert raw_valuation[0]["pe_ttm"] == 99.0
    assert raw_financial[0]["value"] == 0.99
    assert published_valuation["rows"][0]["pe_ttm"] == 12.5
    assert published_financial["rows"][0]["value"] == 0.2


def test_published_coverage_excludes_raw_only_valuation_and_price_assets(monkeypatch) -> None:
    """Alpha coverage is projected from members rather than all persisted facts."""

    observed = datetime(2026, 9, 24, 7, tzinfo=UTC)
    valuation_repository = ValuationFactRepository()
    published_valuation = ValuationFact(
        "000001.SZ",
        observed.date(),
        pe_ttm=12.5,
        source="provider",
        observed_at=observed,
        fetched_at=observed,
        available_at=observed,
    )
    raw_only_valuation = replace(published_valuation, asset_code="600000.SH")
    valuation_repository.bulk_upsert([published_valuation, raw_only_valuation])
    valuation_publication_id = _pin(
        ValuationFactModel.objects.get(asset_code="000001.SZ"),
        "equity.valuation.fact",
        observed_at=observed,
        natural_key="000001.SZ:2026-09-24:provider",
    )

    price_repository = PriceBarRepository()
    published_price = PriceBar(
        "000001.SZ",
        observed.date(),
        10,
        11,
        9,
        10.5,
        source="provider",
    )
    raw_only_price = replace(published_price, asset_code="600000.SH")
    price_repository.bulk_upsert([published_price, raw_only_price])
    price_publication_id = _pin(
        PriceBarModel.objects.get(asset_code="000001.SZ"),
        "equity.price.bar",
        observed_at=observed,
        natural_key="000001.SZ:2026-09-24:1d:none:provider",
    )
    publication_ids = {
        "equity.valuation.fact": valuation_publication_id,
        "equity.price.bar": price_publication_id,
    }
    monkeypatch.setattr(
        public_published_queries,
        "get_current_publication_freshness_gate",
        lambda dataset_key, _publication_key: {
            "publication_id": publication_ids[dataset_key],
            "must_not_use_for_decision": False,
        },
    )
    monkeypatch.setattr(
        public_published_queries,
        "get_canonical_publication_repository",
        CanonicalPublicationRepository,
    )

    assert public_published_queries.list_published_valuation_covered_codes(observed.date()) == [
        "000001.SZ"
    ]
    assert public_published_queries.list_published_price_covered_codes(observed.date()) == [
        "000001.SZ"
    ]


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
