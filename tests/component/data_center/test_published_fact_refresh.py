"""Later ingestion must preserve the exact rows referenced by a publication."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application import public_published_queries, query_services
from apps.data_center.application.publication_utils import (
    publication_hash,
    publication_member_from_reference,
)
from apps.data_center.domain.contracts import (
    DatasetKey,
    PublicationPolicy,
    QuoteMetricSourceContract,
)
from apps.data_center.domain.entities import (
    PriceBar,
    QuoteChangePctEvidence,
    QuoteSnapshot,
    ValuationFact,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
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
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
    publication_fact_reference_for_dataset,
    stored_fact_evidence,
)
from apps.data_center.infrastructure.publication_fact_legacy_payload import (
    quote_snapshot_payload_hash,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.quote_snapshot_repository import QuoteSnapshotRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository
from core.exceptions import DataFetchError

pytestmark = pytest.mark.django_db


def test_quote_null_metric_keeps_v1_digests_and_nonnull_metric_uses_v2() -> None:
    """Adding the nullable metric must preserve every old null quote digest byte."""

    row = QuoteSnapshotModel.objects.create(
        asset_code="000001.SZ",
        snapshot_at=datetime(2026, 10, 23, 7, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 23, 7, 31, tzinfo=UTC),
        current_price="10.0000",
        source="vendor-main",
        raw_payload_hash="",
        change_pct=None,
        extra={},
    )
    legacy_fields = {
        field.attname: _canonical_json_value(getattr(row, field.attname))
        for field in row._meta.concrete_fields
        if field.attname != "change_pct"
    }
    legacy_content = hashlib.sha256(
        json.dumps(
            {
                "encoding": "canonical-fact-row-v1",
                "table": row._meta.db_table,
                "fields": legacy_fields,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    legacy_payload = quote_snapshot_payload_hash(row)

    assert canonical_fact_content_hash(row) == legacy_content

    row.change_pct = 0
    row.contract_version = "2.0"
    row.schema_version = "2.0"
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-a",
    )
    row.extra = {
        "change_pct_source_contract": {
            **source_contract.to_dict(),
            "source_contract_hash": source_contract.content_hash,
            "observed_at": row.snapshot_at.isoformat(),
            "source_value": "0",
            "dataset_contract_key": "equity.quote.snapshot",
            "dataset_contract_version": "2.0",
            "dataset_schema_version": "2.0",
            "metric_value": "0",
            "quote_source": row.source,
        }
    }
    row.save(update_fields=("change_pct", "contract_version", "schema_version", "extra"))

    versioned_content = canonical_fact_content_hash(row)
    versioned_payload = quote_snapshot_payload_hash(row)
    assert versioned_content != legacy_content
    assert versioned_payload != legacy_payload

    changed_source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-b",
    )
    row.extra["change_pct_source_contract"].update(changed_source_contract.to_dict())
    row.extra["change_pct_source_contract"][
        "source_contract_hash"
    ] = changed_source_contract.content_hash
    row.save(update_fields=("extra",))
    assert canonical_fact_content_hash(row) != versioned_content
    assert quote_snapshot_payload_hash(row) != versioned_payload


def test_quote_metric_decimal_roundtrip_preserves_precision_and_zero() -> None:
    """Persisted metric and source evidence retain exact supported Decimal values."""

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="reported_pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="vendor_basis_unverified",
    )
    snapshots: list[QuoteSnapshot] = []
    for asset_code, source_value, metric in (
        ("000001.SZ", "1.234567891234", Decimal("1.234567891234")),
        ("600000.SH", "0", Decimal("0")),
        ("000002.SZ", "123456789012.345", Decimal("123456789012.345")),
    ):
        evidence = QuoteChangePctEvidence(
            metric_value=metric,
            source_value=source_value,
            dataset_contract_key="equity.quote.snapshot",
            dataset_contract_version="2.0",
            dataset_schema_version="2.0",
            source_contract=source_contract,
            source_contract_hash=source_contract.content_hash,
            observed_at=observed_at,
            quote_source="vendor-main",
        )
        snapshots.append(
            QuoteSnapshot(
                asset_code=asset_code,
                snapshot_at=observed_at,
                fetched_at=observed_at,
                current_price=10.25,
                source="vendor-main",
                change_pct=metric,
                change_pct_evidence=evidence,
                contract_version="2.0",
                schema_version="2.0",
            )
        )

    repository = QuoteSnapshotRepository()
    assert repository.bulk_upsert(snapshots) == 3

    for expected in snapshots:
        row = QuoteSnapshotModel.objects.get(asset_code=expected.asset_code)
        loaded = repository.get_latest(expected.asset_code)
        assert loaded is not None
        assert row.change_pct == expected.change_pct
        assert loaded.change_pct == expected.change_pct
        assert loaded.change_pct_evidence == expected.change_pct_evidence
        assert (
            row.extra["change_pct_source_contract"]["source_value"]
            == expected.change_pct_evidence.source_value
        )
        digest = canonical_fact_content_hash(row)
        row.refresh_from_db()
        assert canonical_fact_content_hash(row) == digest


@pytest.mark.parametrize(
    ("asset_code", "metric_text"),
    [
        ("900001.SZ", "1.2345678912345"),
        ("900002.SZ", "1234567890123.456"),
    ],
    ids=["fractional-scale-exceeds-12-places", "significant-digits-exceed-sqlite-bound"],
)
def test_quote_repository_rejects_direct_unrepresentable_metric_before_write(
    asset_code: str,
    metric_text: str,
) -> None:
    """Direct typed evidence cannot bypass exact persistence precision checks."""

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="reported_pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="vendor_basis_unverified",
    )
    metric = Decimal(metric_text)
    evidence = QuoteChangePctEvidence(
        metric_value=metric,
        source_value=metric_text,
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=source_contract,
        source_contract_hash=source_contract.content_hash,
        observed_at=observed_at,
        quote_source="vendor-main",
    )
    quote = QuoteSnapshot(
        asset_code=asset_code,
        snapshot_at=observed_at,
        fetched_at=observed_at,
        current_price=10.25,
        source="vendor-main",
        change_pct=metric,
        change_pct_evidence=evidence,
        contract_version="2.0",
        schema_version="2.0",
    )
    valid_metric = Decimal("1.234567891234")
    valid_evidence = replace(
        evidence,
        metric_value=valid_metric,
        source_value=format(valid_metric, "f"),
    )
    valid_quote = replace(
        quote,
        asset_code="990010.SZ",
        change_pct=valid_metric,
        change_pct_evidence=valid_evidence,
    )
    repository = QuoteSnapshotRepository()
    asset_codes = [valid_quote.asset_code, quote.asset_code]

    assert not QuoteSnapshotModel.objects.filter(asset_code__in=asset_codes).exists()
    with pytest.raises(
        ValueError, match="not exactly representable by the canonical storage field"
    ):
        repository.bulk_upsert([valid_quote, quote])
    assert not QuoteSnapshotModel.objects.filter(asset_code__in=asset_codes).exists()


def test_quote_repository_preserves_raw_response_identity_and_scope() -> None:
    """Persisted quote provenance keeps the provider body hash and metric evidence."""

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    source_contract = QuoteMetricSourceContract(
        provider_source="tushare",
        source_field="pct_chg",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="provider_basis_unverified",
    )
    raw_payload_hash = "b" * 64
    source_record_id = f"tushare:daily:20261023:000001.SZ:{raw_payload_hash[:16]}"
    quote_evidence = QuoteChangePctEvidence(
        metric_value=Decimal("1.234567891234"),
        source_value="1.234567891234",
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=source_contract,
        source_contract_hash=source_contract.content_hash,
        observed_at=observed_at,
        quote_source="tushare",
    )
    quote = QuoteSnapshot(
        asset_code="000001.SZ",
        snapshot_at=observed_at,
        fetched_at=observed_at,
        current_price=12.5,
        source="tushare",
        change_pct=quote_evidence.metric_value,
        change_pct_evidence=quote_evidence,
        contract_version="2.0",
        schema_version="2.0",
        extra={
            "raw_payload_hash": raw_payload_hash,
            "raw_payload_scope": "batch_response_body",
            "source_record_id": source_record_id,
        },
    )

    assert QuoteSnapshotRepository().bulk_upsert([quote]) == 1
    row = QuoteSnapshotModel.objects.get(asset_code=quote.asset_code)
    reference = publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.quote.snapshot",
    )
    stored_evidence = stored_fact_evidence(row)

    assert row.raw_payload_hash == raw_payload_hash
    assert row.source_record_id == source_record_id
    assert reference.raw_payload_hash == raw_payload_hash
    assert reference.source_record_id == source_record_id
    assert stored_evidence.raw_payload_scope == "batch_response_body"
    assert reference.fact_content_hash == stored_evidence.fact_content_hash


def test_quote_raw_payload_hash_precedence_still_binds_new_metric_content() -> None:
    """A source-body hash remains primary while p2 row evidence binds the metric."""

    row = QuoteSnapshotModel.objects.create(
        asset_code="000001.SZ",
        snapshot_at=datetime(2026, 10, 23, 7, 30, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 23, 7, 31, tzinfo=UTC),
        current_price="10.0000",
        source="vendor-main",
        raw_payload_hash="a" * 64,
        source_record_id="quote-response-1",
        change_pct=None,
        extra={},
    )
    before = publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.quote.snapshot",
    )
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="vendor_basis_unverified",
    )
    evidence = QuoteChangePctEvidence(
        metric_value=Decimal("0"),
        source_value="0",
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=source_contract,
        source_contract_hash=source_contract.content_hash,
        observed_at=row.snapshot_at,
        quote_source=row.source,
    )
    row.change_pct = Decimal("0")
    row.contract_version = "2.0"
    row.schema_version = "2.0"
    row.extra = {"change_pct_source_contract": evidence.to_dict()}
    row.save(update_fields=("change_pct", "contract_version", "schema_version", "extra"))
    after = publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.quote.snapshot",
    )

    assert before.raw_payload_hash == after.raw_payload_hash == "a" * 64
    assert before.fact_content_hash != after.fact_content_hash


def test_legacy_p1_quote_read_clears_metric_when_raw_hash_does_not_bind_it() -> None:
    """Keep price from a self-consistent p1 read but never expose its unbound metric."""

    now = datetime.now(UTC)
    observed_at = now - timedelta(seconds=30)
    source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="reported_pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="vendor_basis_unverified",
    )
    metric_evidence = QuoteChangePctEvidence(
        metric_value=Decimal("1.25"),
        source_value="1.25",
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=source_contract,
        source_contract_hash=source_contract.content_hash,
        observed_at=observed_at,
        quote_source="vendor-main",
    )
    quote = QuoteSnapshot(
        asset_code="000001.SZ",
        snapshot_at=observed_at,
        fetched_at=now - timedelta(seconds=10),
        current_price=10.25,
        source="vendor-main",
        change_pct=metric_evidence.metric_value,
        change_pct_evidence=metric_evidence,
        contract_version="2.0",
        schema_version="2.0",
        extra={
            "raw_payload_hash": "c" * 64,
            "raw_payload_scope": "batch_response_body",
            "source_record_id": "vendor-main:response:p1-metric",
        },
    )
    assert QuoteSnapshotRepository().bulk_upsert([quote]) == 1
    row = QuoteSnapshotModel.objects.get(asset_code=quote.asset_code)
    reference = publication_fact_reference_for_dataset(
        row,
        dataset_key="equity.quote.snapshot",
    )

    dataset_key = DatasetKey("equity.quote.snapshot", "2.0", "2.0")
    policy = PublicationPolicy(
        dataset=dataset_key,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "observed_at", "raw_payload_hash"),
        retention_days=3650,
    )
    PublicationPolicyRepository().save(policy)
    DatasetContractModel.objects.create(
        dataset_key=dataset_key.value,
        contract_version=dataset_key.contract_version,
        schema_version=dataset_key.schema_version,
        owner="data-platform",
        frequency="intraday",
        decision_critical=True,
        fields=[
            {
                "name": "change_pct",
                "value_type": "decimal",
                "unit": "percent",
                "nullable": True,
                "zero_allowed": True,
            }
        ],
        freshness_seconds=3600,
        active=True,
    )

    publication_id = uuid4()
    member = publication_member_from_reference(
        reference,
        member_id=str(uuid4()),
        publication_id=str(publication_id),
        dataset_key=dataset_key.value,
    )
    assert row.change_pct == Decimal("1.25")
    assert member.fact_content_hash == canonical_fact_content_hash(row)
    PublicationMemberModel.objects.create(
        member_id=member.member_id,
        publication_id=publication_id,
        dataset_key=member.dataset_key,
        natural_key=member.natural_key,
        source=member.source,
        source_record_id=member.source_record_id,
        fact_table=member.fact_table,
        fact_pk=member.fact_pk,
        observed_at=member.observed_at,
        raw_payload_hash=member.raw_payload_hash,
        quality_status=member.quality_status,
        revision_number=member.revision_number,
        available_at=member.available_at,
        fetched_at=member.fetched_at,
        source_published_at=member.source_published_at,
        raw_payload_scope=member.raw_payload_scope,
        fact_content_hash=member.fact_content_hash,
    )
    assert reference.raw_payload_hash == "c" * 64
    legacy_publication_hash = publication_hash([reference])
    assert publication_hash([replace(reference, fact_content_hash="d" * 64)]) == (
        legacy_publication_hash
    )
    CanonicalPublicationModel.objects.create(
        publication_id=publication_id,
        dataset_key=dataset_key.value,
        publication_key="current",
        policy_version=policy.identity,
        state="published",
        selected_source=quote.source,
        publication_hash=legacy_publication_hash,
        member_count=1,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        as_of=observed_at,
        published_at=now - timedelta(seconds=5),
        created_by="p1-read-contract-test",
    )
    CanonicalPublicationPointerModel.objects.create(
        dataset_key=dataset_key.value,
        publication_key="current",
        publication_id=publication_id,
        publication_hash=legacy_publication_hash,
        activation_id=f"p1-test:{publication_id}",
    )

    result = query_services.query_published_quote_payloads([quote.asset_code])

    assert result["must_not_use_for_decision"] is False
    assert result["policy_identity"] == "2.0:2.0"
    published_rows = result["rows"]
    assert isinstance(published_rows, list)
    published_row = published_rows[0]
    assert published_row["current_price"] == 10.25
    assert published_row["change_pct"] is None
    assert published_row["change_pct_source_contract"] is None
    assert "change_pct_source_contract" not in published_row["extra"]
    assert published_row["extra"]["raw_payload_hash"] == "c" * 64


def test_published_quote_metric_change_creates_successor_revision() -> None:
    """A changed metric under the same contract cannot rewrite the frozen row."""

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    first_source_contract = QuoteMetricSourceContract(
        provider_source="vendor-main",
        source_field="pct",
        origin="vendor_reported",
        source_unit="percent",
        canonical_unit="percent",
        scale_numerator=1,
        scale_denominator=1,
        reference_session="source_quote_observation",
        action_basis="basis-a",
    )
    first_evidence = QuoteChangePctEvidence(
        metric_value=Decimal("0"),
        source_value="0",
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=first_source_contract,
        source_contract_hash=first_source_contract.content_hash,
        observed_at=observed_at,
        quote_source="vendor-main",
    )
    first_quote = QuoteSnapshot(
        asset_code="000001.SZ",
        snapshot_at=observed_at,
        fetched_at=observed_at,
        current_price=10.25,
        source="vendor-main",
        change_pct=Decimal("0"),
        change_pct_evidence=first_evidence,
        contract_version="2.0",
        schema_version="2.0",
    )
    repository = QuoteSnapshotRepository()
    assert repository.bulk_upsert([first_quote]) == 1
    old_row = QuoteSnapshotModel.objects.get(asset_code=first_quote.asset_code)
    old_digest = canonical_fact_content_hash(old_row)
    _pin(old_row, "equity.quote.snapshot")

    second_source_contract = first_source_contract
    second_evidence = QuoteChangePctEvidence(
        metric_value=Decimal("1.234567891234"),
        source_value="1.234567891234",
        dataset_contract_key="equity.quote.snapshot",
        dataset_contract_version="2.0",
        dataset_schema_version="2.0",
        source_contract=second_source_contract,
        source_contract_hash=second_source_contract.content_hash,
        observed_at=observed_at,
        quote_source="vendor-main",
    )
    second_quote = replace(
        first_quote,
        change_pct=second_evidence.metric_value,
        change_pct_evidence=second_evidence,
    )
    assert repository.bulk_upsert([second_quote]) == 1

    old_row.refresh_from_db()
    new_row = QuoteSnapshotModel.objects.exclude(pk=old_row.pk).get(
        asset_code=first_quote.asset_code
    )
    latest = repository.get_latest(first_quote.asset_code)

    assert canonical_fact_content_hash(old_row) == old_digest
    assert old_row.change_pct == Decimal("0")
    assert new_row.change_pct == Decimal("1.234567891234")
    assert new_row.extra["change_pct_source_contract"]["action_basis"] == "basis-a"
    assert latest is not None
    assert latest.change_pct == Decimal("1.234567891234")
    assert latest.change_pct_evidence == second_evidence


def test_published_null_quote_contract_version_change_creates_successor_revision() -> None:
    """A newly synchronized null metric records its real active contract version."""

    observed_at = datetime(2026, 10, 23, 7, 30, tzinfo=UTC)
    first_quote = QuoteSnapshot(
        asset_code="000001.SZ",
        snapshot_at=observed_at,
        fetched_at=observed_at,
        current_price=10.25,
        source="vendor-main",
        contract_version="1.0",
        schema_version="1.0",
    )
    repository = QuoteSnapshotRepository()
    assert repository.bulk_upsert([first_quote]) == 1
    old_row = QuoteSnapshotModel.objects.get(asset_code=first_quote.asset_code)
    old_digest = canonical_fact_content_hash(old_row)
    old_fallback_hash = quote_snapshot_payload_hash(old_row)
    _pin(old_row, "equity.quote.snapshot")

    next_quote = replace(
        first_quote,
        fetched_at=observed_at + timedelta(minutes=1),
        contract_version="2.0",
        schema_version="2.0",
    )
    assert repository.bulk_upsert([next_quote]) == 1

    old_row.refresh_from_db()
    new_row = QuoteSnapshotModel.objects.exclude(pk=old_row.pk).get(
        asset_code=first_quote.asset_code
    )
    latest = repository.get_latest(first_quote.asset_code)

    assert old_row.contract_version == "1.0"
    assert old_row.schema_version == "1.0"
    assert canonical_fact_content_hash(old_row) == old_digest
    assert quote_snapshot_payload_hash(old_row) == old_fallback_hash
    assert new_row.change_pct is None
    assert new_row.contract_version == "2.0"
    assert new_row.schema_version == "2.0"
    assert "change_pct_source_contract" not in new_row.extra
    assert quote_snapshot_payload_hash(new_row) == old_fallback_hash
    assert canonical_fact_content_hash(new_row) != old_digest
    assert latest is not None
    assert latest.contract_version == "2.0"
    assert latest.schema_version == "2.0"


def _canonical_json_value(value: object) -> object:
    """Keep the legacy quote digest oracle independent from the new codec."""

    from apps.data_center.infrastructure.publication_fact_evidence import _canonical_json_value

    return _canonical_json_value(value)


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
    CanonicalPublicationModel.objects.create(
        publication_id=publication_id,
        dataset_key="equity.quote.snapshot",
        publication_key="current",
        policy_version="test-policy",
        publication_hash="f" * 64,
        member_count=1,
        coverage_requested_count=1,
        coverage_eligible_count=1,
        coverage_selected_count=1,
        as_of=observed,
    )
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
