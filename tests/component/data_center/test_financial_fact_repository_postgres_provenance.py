"""Opt-in PostgreSQL round-trip cases for the DATA-02 financial carrier."""

from __future__ import annotations

import os
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import unquote, urlsplit
from uuid import UUID

import pytest
from django.db import connections
from django.db.utils import load_backend

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactDecisionEvidence,
    FinancialFactSourceEvidence,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
    FinancialAvailabilityBasis,
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.financial_fact_repository import (
    FinancialFactProvenanceConflictError,
    FinancialFactRepository,
)
from apps.data_center.infrastructure.models import (
    AssetAliasModel,
    AssetMasterModel,
    FinancialFactModel,
)
from apps.data_center.infrastructure.publication_models import PublicationMemberModel
from tests.component.data_center.test_financial_fact_repository_provenance import (
    test_verified_financial_correction_preserves_publication_and_past_knowledge as _assert_frozen_financial_history,
)

_POSTGRES_FLAG = "AGOM_EVID06_POSTGRES_TEST"
_POSTGRES_URL = "AGOM_EVID06_POSTGRES_TEST_DATABASE_URL"
_DATABASE_NAME = "agom_release_rehearsal_ci"
_ASSET_CODE = "000001.SZ"
_PERIOD_END = date(2026, 6, 30)
_ANNOUNCED_AT = datetime(2026, 9, 14, 8, 0, tzinfo=UTC)
_AVAILABLE_AT = _ANNOUNCED_AT + timedelta(minutes=5)
_SOURCE_HASH = "a" * 64
_SCHEMA_MODELS = (
    AssetMasterModel,
    AssetAliasModel,
    FinancialFactModel,
    PublicationMemberModel,
    DatasetPublicationPolicyModel,
)


def _repository() -> FinancialFactRepository:
    """Build a repository with an independent verifier double for retained fixtures."""

    return FinancialFactRepository(source_time_evidence_verifier=lambda _witness: True)


def _credentials() -> dict[str, object]:
    """Read the already-bound loopback target without exposing its password."""

    if os.environ.get(_POSTGRES_FLAG, "").strip() != "1":
        pytest.skip(f"{_POSTGRES_FLAG}=1 is required for the private PostgreSQL fixture")
    raw_url = os.environ.get(_POSTGRES_URL, "").strip()
    if not raw_url:
        pytest.fail(f"{_POSTGRES_URL} is required")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        pytest.fail("private PostgreSQL URL must use a PostgreSQL scheme")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("private PostgreSQL URL must target loopback")
    if unquote(parsed.path.removeprefix("/")) != _DATABASE_NAME:
        pytest.fail("private PostgreSQL URL database identity mismatch")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": _DATABASE_NAME,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "connect_timeout": 30,
        "sslmode": "disable",
        "gssencmode": "disable",
    }


def _database_observation(wrapper) -> tuple[str, int, int]:
    """Return database identity, public-table count, and other client count."""

    with wrapper.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), "
            "(SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'), "
            "(SELECT COUNT(*) FROM pg_stat_activity "
            "WHERE datname = current_database() "
            "AND backend_type = 'client backend' AND pid <> pg_backend_pid())"
        )
        row = cursor.fetchone()
    if row is None:
        raise AssertionError("private PostgreSQL observation returned no row")
    return str(row[0]), int(row[1]), int(row[2])


@pytest.fixture(scope="module")
def _financial_postgres_schema(django_db_blocker) -> Iterator[None]:
    """Create financial, asset identity and member tables in the empty test DB."""

    credentials = _credentials()
    original = connections["default"]
    database_settings = deepcopy(original.settings_dict)
    database_settings.update(
        ENGINE="django.db.backends.postgresql",
        NAME=_DATABASE_NAME,
        USER=credentials["user"],
        PASSWORD=credentials["password"],
        HOST=credentials["host"],
        PORT=str(credentials["port"]),
        CONN_MAX_AGE=0,
        OPTIONS={
            "connect_timeout": 30,
            "sslmode": "disable",
            "gssencmode": "disable",
        },
    )
    wrapper = load_backend(database_settings["ENGINE"]).DatabaseWrapper(
        database_settings,
        alias="default",
    )
    created = False
    with django_db_blocker.unblock():
        connections["default"] = wrapper
        try:
            if wrapper.vendor != "postgresql":
                pytest.fail("financial fixture resolved a non-PostgreSQL backend")
            database_name, table_count, other_clients = _database_observation(wrapper)
            assert database_name == _DATABASE_NAME
            assert table_count == 0
            assert other_clients == 0
            with wrapper.schema_editor() as editor:
                for model in _SCHEMA_MODELS:
                    editor.create_model(model)
            created = True
            assert set(wrapper.introspection.table_names()) == {
                model._meta.db_table for model in _SCHEMA_MODELS
            }
            yield
        finally:
            if created:
                wrapper.rollback()
                with wrapper.schema_editor() as editor:
                    for model in reversed(_SCHEMA_MODELS):
                        editor.delete_model(model)
                database_name, table_count, other_clients = _database_observation(wrapper)
                assert database_name == _DATABASE_NAME
                assert table_count == 0
                assert other_clients == 0
            wrapper.close()
            connections["default"] = original


@pytest.fixture(autouse=True)
def _clear_financial_rows(_financial_postgres_schema) -> Iterator[None]:
    """Keep each case row-isolated while the module owns its test tables."""

    FinancialFactModel.objects.all().delete()
    PublicationMemberModel.objects.all().delete()
    AssetAliasModel.objects.all().delete()
    AssetMasterModel.objects.all().delete()
    DatasetPublicationPolicyModel.objects.all().delete()
    yield
    PublicationMemberModel.objects.all().delete()
    FinancialFactModel.objects.all().delete()
    AssetAliasModel.objects.all().delete()
    AssetMasterModel.objects.all().delete()
    DatasetPublicationPolicyModel.objects.all().delete()


def test_postgres_financial_revision_preserves_frozen_rows_and_past_knowledge() -> None:
    _assert_frozen_financial_history()


def _evidence() -> FinancialFactSourceEvidence:
    """Build one complete three-field source witness."""

    return FinancialFactSourceEvidence(
        announced_at=_ANNOUNCED_AT,
        source_record_id="pg-vendor-record-1",
        raw_payload_hash=_SOURCE_HASH,
    )


def _fact(
    *, metric_code: str, value: float, evidence: FinancialFactSourceEvidence | None = None
) -> FinancialFact:
    """Build one financial fact with explicit source timing and optional witness."""

    decision_evidence = None
    if evidence is not None:
        response = FinancialResponseEvidence(
            body_sha256=evidence.raw_payload_hash or _SOURCE_HASH,
            body_size_bytes=128,
            response_completed_at=_AVAILABLE_AT + timedelta(minutes=1),
            request_scope=FinancialRequestScope(
                provider_name="provider-main",
                dataset_key="equity.financial.fact",
                asset_code=_ASSET_CODE,
                period_limit=1,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=(_ASSET_CODE,),
                period_ends=(_PERIOD_END,),
                row_count=1,
            ),
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        )
        decision_evidence = FinancialFactDecisionEvidence(
            artifact_reference=FinancialResponseArtifactRef(
                capture_id=UUID("50000000-0000-4000-8000-000000000001"),
                location="financial-response/postgres-provenance.bin",
                evidence=response,
                format_version="financial-response-artifact.v1",
                encryption_algorithm="fernet",
                encryption_key_ref="config_center.data02.test-key",
                encryption_key_version="v1",
            ),
            native_asset_code=_ASSET_CODE,
            native_period_end=_PERIOD_END,
            native_row_id=evidence.source_record_id or "pg-vendor-record-1",
            source_time_witness=FinancialSourceTimeWitness(
                artifact_reference=FinancialSourceTimeArtifactRef(
                    capture_id=UUID("50000000-0000-4000-8000-000000000002"),
                    location="financial-source-time/postgres-provenance.bin",
                    provider_name="provider-main",
                    dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
                    requested_asset_code=_ASSET_CODE,
                    requested_announcement_date=_ANNOUNCED_AT.date(),
                    body_sha256="b" * 64,
                    body_size_bytes=96,
                    response_completed_at=_AVAILABLE_AT + timedelta(minutes=1),
                    response_row_count=1,
                    format_version="financial-source-time-artifact.v1",
                    encryption_algorithm="fernet",
                    encryption_key_ref="config_center.data02.test-key",
                    encryption_key_version="v1",
                ),
                native_asset_code=_ASSET_CODE,
                native_period_end=_PERIOD_END,
                financial_native_row_id=evidence.source_record_id or "pg-vendor-record-1",
                financial_announced_date=_ANNOUNCED_AT.date(),
                source_native_row_id="provider-main:notice:pg-vendor-record-1",
                source_timezone="UTC",
                announced_at=_ANNOUNCED_AT,
                available_at=_AVAILABLE_AT,
                row_projection_sha256="c" * 64,
                governed_match_contract_id="provider-main.financial-announcement.exact",
                governed_match_contract_version="v1",
                governed_match_contract_sha256="d" * 64,
                matched_row_count=1,
                availability_basis=FinancialAvailabilityBasis.PROVIDER_NATIVE_EXACT,
            ),
        )
    return FinancialFact(
        asset_code=_ASSET_CODE,
        period_end=_PERIOD_END,
        period_type=FinancialPeriodType.QUARTERLY,
        metric_code=metric_code,
        value=value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=_AVAILABLE_AT,
        source_evidence=evidence,
        decision_evidence=decision_evidence,
    )


def _direct_model_row(*, metric_code: str, value: float) -> FinancialFactModel:
    """Persist one direct float model value as the backend storage oracle."""

    row = FinancialFactModel.objects.create(
        asset_code=_ASSET_CODE,
        period_end=_PERIOD_END,
        period_type="quarterly",
        metric_code=metric_code,
        value=value,
        unit="CNY",
        source="provider-main",
        report_date=date(2026, 9, 13),
        available_at=_AVAILABLE_AT,
    )
    row.refresh_from_db()
    return row


def test_financial_repository_round_trip_and_replay_count_on_postgresql() -> None:
    """PostgreSQL storage matches the direct writer and replay performs no write."""

    oracle = _direct_model_row(metric_code="pg_oracle", value=12.34525)
    fact = _fact(metric_code="pg_repository", value=12.34525, evidence=_evidence())
    repository = _repository()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code="pg_repository")
    assert row.value == oracle.value
    assert row.announced_at == _ANNOUNCED_AT
    assert row.source_record_id == "pg-vendor-record-1"
    assert row.raw_payload_hash == _SOURCE_HASH
    fetched_at = row.fetched_at

    assert repository.bulk_upsert([fact]) == 0
    row.refresh_from_db()
    assert row.value == oracle.value
    assert row.fetched_at == fetched_at


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(12.03125, id="positive_12_03125"),
        pytest.param(-12.03125, id="negative_12_03125"),
        pytest.param(12.34505, id="positive_12_34505"),
        pytest.param(12.34525, id="positive_12_34525"),
        pytest.param(12.34535, id="positive_12_34535"),
    ],
)
def test_repository_float_ties_match_direct_postgresql_writer(value: float) -> None:
    """Every tie value follows the unchanged ORM writer and replays as a no-op."""

    oracle = _direct_model_row(metric_code="pg_tie_oracle", value=value)
    fact = _fact(metric_code="pg_tie_repository", value=value, evidence=_evidence())
    repository = _repository()

    assert repository.bulk_upsert([fact]) == 1
    row = FinancialFactModel.objects.get(metric_code="pg_tie_repository")
    assert row.value == oracle.value
    fetched_at = row.fetched_at
    assert row.announced_at == _ANNOUNCED_AT
    assert row.source_record_id == "pg-vendor-record-1"
    assert row.raw_payload_hash == _SOURCE_HASH

    assert repository.bulk_upsert([fact]) == 0
    row.refresh_from_db()
    assert row.value == oracle.value
    assert row.fetched_at == fetched_at


def test_financial_repository_stale_witness_rolls_back_postgresql_batch() -> None:
    """A stale protected row blocks the batch before its new row can remain."""

    protected = _direct_model_row(metric_code="pg_protected", value=100.0)
    protected.announced_at = _ANNOUNCED_AT
    protected.source_record_id = "pg-old-record"
    protected.raw_payload_hash = _SOURCE_HASH
    protected.save(update_fields=["announced_at", "source_record_id", "raw_payload_hash"])
    replacement = _fact(metric_code="pg_protected", value=101.0, evidence=_evidence())
    new_fact = _fact(metric_code="pg_new", value=1.0, evidence=_evidence())

    with pytest.raises(FinancialFactProvenanceConflictError, match="raw payload"):
        _repository().bulk_upsert([replacement, new_fact])

    protected.refresh_from_db()
    assert protected.value == Decimal("100.0000")
    assert protected.raw_payload_hash == _SOURCE_HASH
    assert not FinancialFactModel.objects.filter(metric_code="pg_new").exists()
