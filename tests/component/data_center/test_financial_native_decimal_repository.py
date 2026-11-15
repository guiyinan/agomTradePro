"""Exact numeric storage, immutable revisions and migration rollback protection."""

import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from rest_framework.test import APIClient

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_numeric_evidence import (
    FinancialMetricSourceContract,
    NativeFinancialMetricObservation,
)
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import FinancialFactModel
from apps.data_center.infrastructure.publication_fact_evidence import canonical_fact_content_hash
from apps.data_center.infrastructure.publication_fact_legacy_payload import financial_payload_hash
from apps.data_center.infrastructure.publication_models import PublicationMemberModel
from tests.component.data_center.test_financial_fact_repository_provenance import (
    _evidence,
    _publication_fact,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db


def _as_native(fact: FinancialFact, value: str = "1.775599913526") -> FinancialFact:
    source = fact.source_evidence
    assert source is not None
    evidence = NativeFinancialMetricObservation.from_raw_value(
        contract=FinancialMetricSourceContract(
            provider=fact.source,
            dataset_key="equity.financial.fact",
            metric_code=fact.metric_code,
            source_field="NATIVE_REVENUE",
            source_unit=fact.unit,
            canonical_unit=fact.unit,
            scale_numerator=1,
            scale_denominator=1,
            contract_version="test-exact-1",
            origin="native",
        ),
        raw_value=value,
        source_field="NATIVE_REVENUE",
        body_sha256=source.raw_payload_hash,
        native_row_id=source.source_record_id,
    )
    return replace(
        fact,
        value=Decimal(value),
        numeric_schema="native-decimal-v2",
        numeric_evidence=evidence,
    )


def _repository() -> FinancialFactRepository:
    """Orchestration doubles; independent byte verification is tested separately."""
    return FinancialFactRepository(
        source_time_evidence_verifier=lambda _: True,
        numeric_evidence_verifier=lambda _: True,
    )


def test_exact_native_roundtrip_keeps_four_place_column_null_and_replays_without_update() -> None:
    repository = _repository()
    fact = _as_native(_publication_fact())
    assert repository.bulk_upsert([fact]) == 1
    stored = FinancialFactModel.objects.get()
    assert stored.value is None
    assert stored.exact_value_text == "1.775599913526"
    assert stored.numeric_evidence == fact.numeric_evidence.to_dict()
    loaded = repository.get_latest(fact.asset_code)
    assert loaded is not None and type(loaded.value) is Decimal
    assert loaded.to_dict()["value"] == "1.775599913526"
    references = repository.list_publication_candidates([loaded])
    assert len(references) == 1
    assert references[0].fact_content_hash == canonical_fact_content_hash(stored)
    assert references[0].raw_payload_hash == "a" * 64
    assert repository.bulk_upsert([loaded]) == 0
    assert FinancialFactModel.objects.count() == 1


def test_unpinned_native_correction_appends_and_preserves_past_knowledge() -> None:
    repository = _repository()
    fact = _as_native(_publication_fact())
    repository.bulk_upsert([fact])
    old = FinancialFactModel.objects.get()
    old_hash = canonical_fact_content_hash(old)
    old_known_at = old.fetched_at
    corrected = _as_native(
        _publication_fact(source_evidence=_evidence(raw_payload_hash="b" * 64)), "2.000000000001"
    )
    assert repository.bulk_upsert([corrected]) == 1
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == old_hash
    assert old.fetched_at == old_known_at
    assert FinancialFactModel.objects.count() == 2
    assert repository.get_latest(fact.asset_code).value == Decimal("2.000000000001")
    past = repository.get_facts(fact.asset_code, knowledge_cutoff=old_known_at)
    assert len(past) == 1 and past[0].value == Decimal("1.775599913526")


def test_verified_legacy_to_native_upgrade_preserves_old_row_and_hash() -> None:
    repository = _repository()
    legacy = _publication_fact(value=1.7756)
    repository.bulk_upsert([legacy])
    old = FinancialFactModel.objects.get()
    digest = canonical_fact_content_hash(old)
    assert repository.bulk_upsert([_as_native(legacy)]) == 1
    old.refresh_from_db()
    assert canonical_fact_content_hash(old) == digest
    assert old.value == Decimal("1.7756")
    assert FinancialFactModel.objects.count() == 2


def test_native_cannot_be_downgraded_or_read_without_independent_verification() -> None:
    repository = _repository()
    native = _as_native(_publication_fact())
    repository.bulk_upsert([native])
    with pytest.raises(FinancialFactProvenanceConflictError, match="downgrade"):
        repository.bulk_upsert([_publication_fact()])
    unqualified = FinancialFactRepository(source_time_evidence_verifier=lambda _: True)
    with pytest.raises(FinancialFactProvenanceConflictError, match="native financial read"):
        unqualified.get_latest(native.asset_code)
    with pytest.raises(FinancialFactProvenanceConflictError, match="native financial publication"):
        unqualified.list_publication_candidates([native])


def test_unverified_native_member_blocks_entire_batch_before_any_write() -> None:
    fact = _publication_fact()
    repository = FinancialFactRepository(source_time_evidence_verifier=lambda _: True)
    with pytest.raises(FinancialFactProvenanceConflictError, match="independent catalog"):
        repository.bulk_upsert([replace(fact, metric_code="other"), _as_native(fact)])
    assert FinancialFactModel.objects.count() == 0


def test_numeric_requalification_failure_blocks_previously_stored_native_reads() -> None:
    repository = _repository()
    fact = _as_native(_publication_fact())
    repository.bulk_upsert([fact])
    unqualified = FinancialFactRepository(
        source_time_evidence_verifier=lambda _: True,
        numeric_evidence_verifier=lambda _: False,
    )
    with pytest.raises(FinancialFactProvenanceConflictError):
        unqualified.get_facts(fact.asset_code)
    with pytest.raises(FinancialFactProvenanceConflictError):
        unqualified.list_current_publication_candidates((fact.asset_code,))


def test_real_query_and_http_json_preserve_native_decimal_text(
    monkeypatch: pytest.MonkeyPatch, django_user_model: type[models.Model]
) -> None:
    from apps.data_center.application import query_services
    from apps.data_center.application.fact_query_use_cases import QueryFinancialsUseCase
    from apps.data_center.interface import api_views

    repository = _repository()
    native = _as_native(_publication_fact())
    repository.bulk_upsert([native])
    row = FinancialFactModel.objects.get()
    monkeypatch.setattr(query_services, "get_financial_fact_repository", lambda: repository)
    queried = query_services.query_financial_facts(native.asset_code, fact_pks=[str(row.pk)])
    assert queried[0]["value"] == "1.775599913526"
    monkeypatch.setattr(
        api_views, "make_query_financials_use_case", lambda: QueryFinancialsUseCase(repository)
    )
    user = django_user_model.objects.create_user(username="native-financial-reader")
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(
        "/api/data-center/financials/", {"asset_code": native.asset_code, "mode": "historical"}
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["data"][0]["value"] == "1.775599913526"
    assert response.json()["data"][0]["numeric_schema"] == "native-decimal-v2"


@pytest.mark.parametrize(
    "changes",
    [
        {"numeric_schema": "unknown"},
        {"value": Decimal("1.7756")},
        {"exact_value_text": None},
        {"exact_value_text": ""},
        {"numeric_evidence": None},
        {"numeric_evidence": {}},
        {"numeric_evidence": []},
        {"numeric_evidence": "not-an-object"},
        {"numeric_evidence": models.Value(None, output_field=models.JSONField())},
    ],
)
def test_database_rejects_incomplete_or_mixed_native_storage(changes: dict[str, object]) -> None:
    native = _as_native(_publication_fact())
    payload = {
        "asset_code": native.asset_code,
        "period_end": native.period_end,
        "period_type": native.period_type.value,
        "metric_code": native.metric_code,
        "source": native.source,
        "unit": native.unit,
        "value": None,
        "numeric_schema": "native-decimal-v2",
        "exact_value_text": "1.775599913526",
        "numeric_evidence": native.numeric_evidence.to_dict(),
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        FinancialFactModel.objects.create(**(payload | changes))


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_refuses_before_discarding_native_columns() -> None:
    if connection.vendor == "postgresql":
        assert_native_postgres_test_database()
    repository = _repository()
    repository.bulk_upsert([_as_native(_publication_fact())])
    with pytest.raises(IrreversibleError, match="Native financial rows exist"):
        MigrationExecutor(connection).migrate([("data_center", "0113_institutional_calendar")])
    assert ("data_center", "0114_financial_native_decimal_storage") in MigrationRecorder(
        connection
    ).applied_migrations()
    assert FinancialFactModel.objects.get().exact_value_text == "1.775599913526"


@pytest.mark.django_db(transaction=True)
def test_migration_preserves_populated_legacy_facts_and_frozen_members() -> None:
    """Exercise real populated old storage rather than only post-migration goldens."""
    if connection.vendor == "postgresql":
        assert_native_postgres_test_database()
    executor = MigrationExecutor(connection)
    executor.migrate([("data_center", "0113_institutional_calendar")])
    historical = executor.loader.project_state(
        [("data_center", "0113_institutional_calendar")]
    ).apps
    old_model = historical.get_model("data_center", "FinancialFactModel")
    old_member = historical.get_model("data_center", "PublicationMemberModel")
    assert len(old_model._meta.concrete_fields) == 21
    expected: list[tuple[int, Decimal, str, str]] = []
    try:
        for number, value in enumerate(("12.3400", "0.0000", "-0.0100", "9999999999999.9999")):
            row = old_model.objects.create(
                asset_code="000001.SZ",
                period_end=date(2026, 6, 30),
                period_type="semi_annual",
                metric_code=f"migration-metric-{number}",
                value=Decimal(value),
                unit="CNY",
                source="legacy-source",
            )
            row.refresh_from_db()
            assert not isinstance(row, FinancialFactModel)
            # The generic historical-model branch is the original 21-column v1 codec.
            old_hash = canonical_fact_content_hash(row)
            legacy_payload = {
                "asset_code": row.asset_code,
                "period_end": row.period_end.isoformat(),
                "period_type": row.period_type,
                "metric_code": row.metric_code,
                "value": str(row.value),
                "unit": row.unit,
                "source": row.source,
                "report_date": None,
                "available_at": None,
            }
            fallback = hashlib.sha256(
                json.dumps(legacy_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            key = f"{row.asset_code}:{row.period_end}:{row.period_type}:{row.metric_code}:{row.source}"
            old_member.objects.create(
                publication_id=uuid4(),
                dataset_key="equity.financial.fact",
                natural_key=key,
                source=row.source,
                source_record_id=key,
                fact_table=row._meta.db_table,
                fact_pk=str(row.pk),
                fact_content_hash=old_hash,
                raw_payload_hash=fallback,
            )
            expected.append((row.pk, row.value, old_hash, fallback))
    finally:
        MigrationExecutor(connection).migrate(
            [("data_center", "0114_financial_native_decimal_storage")]
        )
    for primary_key, value, digest, fallback in expected:
        migrated = FinancialFactModel.objects.get(pk=primary_key)
        assert migrated.value == value
        assert migrated.numeric_schema == "legacy-decimal-v1"
        assert migrated.exact_value_text is None and migrated.numeric_evidence is None
        assert canonical_fact_content_hash(migrated) == digest
        assert financial_payload_hash(migrated) == fallback
        member = PublicationMemberModel.objects.get(fact_pk=str(primary_key))
        assert member.fact_content_hash == digest and member.raw_payload_hash == fallback
    # A still-running legacy writer omits the new columns during expand-first rollout.
    old_writer_row = old_model.objects.create(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        period_type="semi_annual",
        metric_code="legacy-writer-after-upgrade",
        value=Decimal("7.0000"),
        unit="CNY",
        source="legacy-source",
    )
    upgraded = FinancialFactModel.objects.get(pk=old_writer_row.pk)
    assert upgraded.numeric_schema == "legacy-decimal-v1"
    assert upgraded.value == Decimal("7.0000")
    assert upgraded.exact_value_text is None and upgraded.numeric_evidence is None
