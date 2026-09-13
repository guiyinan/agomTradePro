"""Financial fact source-field round trips and stale-witness write guards."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import FinancialFactModel

pytestmark = pytest.mark.django_db

ASSET_CODE = "000001.SZ"
PERIOD_END = date(2026, 6, 30)
ANNOUNCED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
AVAILABLE_AT = ANNOUNCED_AT + timedelta(minutes=5)
SOURCE_HASH_A = "a" * 64
SOURCE_HASH_B = "b" * 64


def _evidence(
    *,
    announced_at: datetime = ANNOUNCED_AT,
    source_record_id: str = "vendor-record-1",
    raw_payload_hash: str = SOURCE_HASH_A,
) -> FinancialFactSourceEvidence:
    """Build the typed evidence attached to an existing source row."""

    return FinancialFactSourceEvidence(
        announced_at=announced_at,
        source_record_id=source_record_id,
        raw_payload_hash=raw_payload_hash,
    )


def _fact(
    *,
    metric_code: str = "revenue",
    value: float = 123.45,
    unit: str = "CNY",
    report_date: date | None = date(2026, 9, 13),
    available_at: datetime | None = AVAILABLE_AT,
    source_evidence: FinancialFactSourceEvidence | None = None,
) -> FinancialFact:
    """Build one domain fact while keeping source timestamps explicit."""

    return FinancialFact(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=value,
        unit=unit,
        source="provider-main",
        report_date=report_date,
        available_at=available_at,
        source_evidence=source_evidence,
    )


def _stored_row(*, value: str = "123.4500") -> FinancialFactModel:
    """Create a row carrying a real-looking but independently supplied witness."""

    return FinancialFactModel.objects.create(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="revenue",
        value=Decimal(value),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=AVAILABLE_AT,
        announced_at=ANNOUNCED_AT,
        source_record_id="vendor-record-1",
        raw_payload_hash=SOURCE_HASH_A,
    )


def test_repository_round_trips_existing_source_fields() -> None:
    """Repository/domain conversion preserves source ID, hash, and announcement."""

    row = _stored_row()
    fact = FinancialFactRepository().get_latest(ASSET_CODE, FinancialPeriodType.QUARTERLY)

    assert fact is not None
    assert fact.source_evidence == _evidence()
    assert fact.available_at == row.available_at

    assert FinancialFactRepository().bulk_upsert([fact]) == 0
    row.refresh_from_db()

    assert row.announced_at == ANNOUNCED_AT
    assert row.source_record_id == "vendor-record-1"
    assert row.raw_payload_hash == SOURCE_HASH_A


def test_stale_witness_blocks_entire_batch_before_any_dml() -> None:
    """A changed value without replacement evidence cannot keep the old witness."""

    row = _stored_row()
    before = list(FinancialFactModel.objects.values())
    replacement_candidate = _fact(value=999.0)
    new_candidate = FinancialFact(
        asset_code=ASSET_CODE,
        period_end=date(2026, 3, 31),
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code="net_profit",
        value=10.0,
        unit="CNY",
        source="provider-main",
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="stale"):
        FinancialFactRepository().bulk_upsert([replacement_candidate, new_candidate])

    assert list(FinancialFactModel.objects.values()) == before
    assert FinancialFactModel.objects.count() == 1
    row.refresh_from_db()
    assert row.value == Decimal("123.4500")
    assert row.raw_payload_hash == SOURCE_HASH_A


def test_same_raw_hash_cannot_prove_changed_normalized_value() -> None:
    """A changed value with the same body hash is rejected even with complete metadata."""

    _stored_row()
    changed_with_same_body = _fact(value=999.0, source_evidence=_evidence())

    with pytest.raises(FinancialFactProvenanceConflictError, match="raw payload"):
        FinancialFactRepository().bulk_upsert([changed_with_same_body])

    assert FinancialFactModel.objects.get().value == Decimal("123.4500")


def test_complete_source_replacement_updates_fact_and_source_fields_atomically() -> None:
    """A new body hash and complete source witness may replace the old row evidence."""

    row = _stored_row()
    new_announced = ANNOUNCED_AT + timedelta(days=1)
    replacement = _fact(
        value=999.0,
        report_date=date(2026, 9, 14),
        available_at=new_announced + timedelta(minutes=5),
        source_evidence=_evidence(
            announced_at=new_announced,
            source_record_id="vendor-record-2",
            raw_payload_hash=SOURCE_HASH_B,
        ),
    )

    assert FinancialFactRepository().bulk_upsert([replacement]) == 1
    row.refresh_from_db()

    assert row.value == Decimal("999.0000")
    assert row.report_date == date(2026, 9, 14)
    assert row.available_at == new_announced + timedelta(minutes=5)
    assert row.announced_at == new_announced
    assert row.source_record_id == "vendor-record-2"
    assert row.raw_payload_hash == SOURCE_HASH_B


def test_partial_replacement_evidence_is_blocked_without_clearing_old_fields() -> None:
    """Partial metadata cannot authorize a changed value or clear old evidence."""

    row = _stored_row()
    partial = _fact(
        value=999.0,
        source_evidence=FinancialFactSourceEvidence(raw_payload_hash=SOURCE_HASH_B),
    )

    with pytest.raises(FinancialFactProvenanceConflictError, match="complete"):
        FinancialFactRepository().bulk_upsert([partial])

    row.refresh_from_db()
    assert row.value == Decimal("123.4500")
    assert row.announced_at == ANNOUNCED_AT
    assert row.source_record_id == "vendor-record-1"
    assert row.raw_payload_hash == SOURCE_HASH_A


def test_existing_batch_locks_and_updates_with_bounded_query_count() -> None:
    """Existing rows are read in one chunk and changed with one bulk update."""

    metric_codes = [f"metric_{index}" for index in range(4)]
    for metric_code in metric_codes:
        FinancialFactModel.objects.create(
            asset_code=ASSET_CODE,
            period_end=PERIOD_END,
            period_type="quarterly",
            metric_code=metric_code,
            value=Decimal("123.4500"),
            unit="CNY",
            source="provider-main",
            report_date=date(2026, 9, 13),
            available_at=AVAILABLE_AT,
        )
    facts = [_fact(metric_code=metric_code, value=124.45) for metric_code in metric_codes]

    with CaptureQueriesContext(connection) as queries:
        assert FinancialFactRepository().bulk_upsert(facts) == len(facts)

    select_queries = [
        query["sql"] for query in queries if query["sql"].lstrip().upper().startswith("SELECT")
    ]
    update_queries = [
        query["sql"] for query in queries if query["sql"].lstrip().upper().startswith("UPDATE")
    ]
    assert len(select_queries) == 1
    assert len(update_queries) == 1
    assert set(FinancialFactModel.objects.values_list("metric_code", flat=True)) == set(
        metric_codes
    )


def test_decimalfield_storage_normalization_allows_precise_first_insert_and_replay() -> None:
    """A Domain value beyond model scale can be inserted and replayed safely."""

    fact = _fact(metric_code="precise", value=12.34567)
    repository = FinancialFactRepository()
    oracle = FinancialFactModel.objects.create(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="precise_oracle",
        value=fact.value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=AVAILABLE_AT,
    )
    oracle.refresh_from_db()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code="precise")
    stored_value = row.value
    fetched_at = row.fetched_at
    assert row.value == oracle.value

    assert repository.bulk_upsert([fact]) == 0
    row.refresh_from_db()

    assert row.value == stored_value
    assert row.fetched_at == fetched_at


@pytest.mark.parametrize(
    ("value", "sqlite_storage", "postgresql_storage"),
    [
        (12.03125, Decimal("12.0312"), Decimal("12.0313")),
        (-12.03125, Decimal("-12.0312"), Decimal("-12.0313")),
        (12.34505, Decimal("12.3450"), Decimal("12.3451")),
        (12.34525, Decimal("12.3452"), Decimal("12.3453")),
        (12.34535, Decimal("12.3454"), Decimal("12.3453")),
    ],
)
def test_decimalfield_float_ties_follow_model_conversion_on_insert_and_replay(
    value: float,
    sqlite_storage: Decimal,
    postgresql_storage: Decimal,
) -> None:
    """Repository writes match direct model storage at backend-specific ties."""

    metric_code = f"tie_{str(value).replace('.', '_')}"
    fact = _fact(metric_code=metric_code, value=value)
    repository = FinancialFactRepository()
    oracle = FinancialFactModel.objects.create(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code=f"{metric_code}_oracle",
        value=value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=AVAILABLE_AT,
    )
    oracle.refresh_from_db()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code=metric_code)
    assert row.value == oracle.value
    expected_by_vendor = {
        "sqlite": sqlite_storage,
        "postgresql": postgresql_storage,
    }
    expected_storage = expected_by_vendor.get(connection.vendor)
    if expected_storage is not None:
        assert oracle.value == expected_storage

    assert repository.bulk_upsert([fact]) == 0


def test_mixed_batch_counts_only_changed_rows_and_preserves_noop_row() -> None:
    """A replay plus a change reports one write and leaves replay metadata intact."""

    unchanged = FinancialFactModel.objects.create(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="unchanged",
        value=Decimal("123.4500"),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=AVAILABLE_AT,
    )
    changed = FinancialFactModel.objects.create(
        asset_code=ASSET_CODE,
        period_end=PERIOD_END,
        period_type="quarterly",
        metric_code="changed",
        value=Decimal("123.4500"),
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=AVAILABLE_AT,
    )
    unchanged_fetched_at = unchanged.fetched_at
    changed_fetched_at = changed.fetched_at

    count = FinancialFactRepository().bulk_upsert(
        [
            _fact(metric_code="unchanged", value=123.45),
            _fact(metric_code="changed", value=124.45),
        ]
    )

    assert count == 1
    unchanged.refresh_from_db()
    changed.refresh_from_db()
    assert unchanged.value == Decimal("123.4500")
    assert unchanged.fetched_at == unchanged_fetched_at
    assert changed.value == Decimal("124.4500")
    assert changed.fetched_at == changed_fetched_at
