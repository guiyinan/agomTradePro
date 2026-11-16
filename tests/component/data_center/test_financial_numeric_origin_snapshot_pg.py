"""Native PostgreSQL contracts for capture-time configured-origin snapshots.

These synthetic fixtures exercise the real provider, publisher, 0116 capture,
successful Egress Audit, Statutory Source repository, and retained-body store.
They establish no legal status, Owner approval, or production financial gate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.db import (
    DEFAULT_DB_ALIAS,
    DatabaseError,
    IntegrityError,
    connection,
    connections,
    transaction,
)
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor

from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    ProviderDocumentResponseCapture,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceBodyReference,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure.egress_models import EgressRequestAuditModel
from apps.data_center.infrastructure.financial_availability_source_reader import (
    DjangoFinancialAvailabilitySourceReader,
)
from apps.data_center.infrastructure.financial_numeric_catalog_capture_repository import (
    DjangoFinancialNumericSourceCaptureRepository,
)
from apps.data_center.infrastructure.financial_numeric_catalog_models import (
    FinancialNumericSourceDocumentCaptureModel,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_codec import (
    decode_origin_snapshot,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_reader import (
    DjangoFinancialNumericOriginSnapshotReader,
    FinancialNumericOriginSnapshotError,
)
from apps.data_center.infrastructure.financial_statutory_numeric_capture_retention import (
    FinancialStatutoryNumericPairCaptureRepository,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStore,
)
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
    StatutorySourceDocumentRevisionModel,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "apps.data_center",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
        ],
    ),
]

_BODY = b"synthetic configured SZSE source PDF for origin snapshot mechanics"
_HOST = "www.szse.cn"
_REGION = "isolated-origin-snapshot-test"


@dataclass(frozen=True, slots=True)
class _CapturePair:
    """One same-response statutory/numeric capture pair and its repositories."""

    capture_id: UUID
    provider: ProviderConfigModel
    profile_json: dict[str, object]
    numeric_repository: DjangoFinancialNumericSourceCaptureRepository
    source_reader: DjangoFinancialAvailabilitySourceReader
    source_repository: DjangoStatutorySourceRepository
    identity: FinancialStatutorySourceIdentity
    source_capture: StatutorySourceCaptureReference
    body_store: StatutorySourceBodyStore
    recorded_at: datetime


def _database_now() -> datetime:
    """Read database wall clock for explicit PostgreSQL cutoff assertions."""

    if connection.vendor != "postgresql":
        pytest.skip("origin snapshot contracts require native PostgreSQL")
    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is datetime and row[0].tzinfo is not None
    return row[0].astimezone(UTC)


def _profile_json(
    *,
    capture_id: UUID,
    body_sha256: str,
    body_size_bytes: int,
    publisher_code: str,
    source_version: str,
) -> dict[str, object]:
    """Build the exact existing v1 profile shape from the real source revision."""

    return {
        "schema_version": "data_center.statutory_source_catalog.v1",
        "profile_id": f"synthetic-origin-{capture_id.hex}",
        "version": "test-profile-v1",
        "publisher_code": publisher_code,
        "enabled": True,
        "allowed_hosts": [_HOST],
        "max_capture_age_seconds": 3600,
        "documents": [
            {
                "revision": {
                    "document_id": f"synthetic-origin-{capture_id.hex}",
                    "source_version": source_version,
                    "canonical_url": f"https://{_HOST}/lawrules/{capture_id.hex}.pdf",
                    "issuer": "SZSE",
                    "title": "Synthetic configured source",
                    "legal_number": "SYNTHETIC-ORIGIN-PG",
                    "publication_date": {"precision": "date", "value": "2026-11-15"},
                    "effective_date": {"precision": "date", "value": "2026-11-16"},
                    "body_sha256": body_sha256,
                    "body_size_bytes": body_size_bytes,
                },
                "max_bytes": body_size_bytes + 100,
                "allowed_media_types": ["application/pdf"],
            }
        ],
    }


def _capture_pair(
    tmp_path: Path, *, profile_mode: str = "matching", capture_id: UUID | None = None
) -> _CapturePair:
    """Persist one real same-response source and numeric capture pair."""

    assert_native_postgres_test_database()
    body_store = StatutorySourceBodyStore(tmp_path / "bodies", max_body_bytes=4096)
    source_repository = DjangoStatutorySourceRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    numeric_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    capture_id = uuid4() if capture_id is None else capture_id
    body_sha256 = hashlib.sha256(_BODY).hexdigest()
    source_version = "test-native-rules-v1"
    publisher_code = f"SZSET{capture_id.hex[:18]}"
    profile_json = _profile_json(
        capture_id=capture_id,
        body_sha256=body_sha256,
        body_size_bytes=len(_BODY),
        publisher_code=publisher_code,
        source_version=source_version,
    )
    provider_extra_config: dict[str, object] = {
        "statutory_source_catalog": profile_json,
        "fixture_secret_marker": "must-never-be-copied-to-origin-snapshot",
    }
    if profile_mode == "missing":
        provider_extra_config = {"fixture_secret_marker": "not-a-profile"}
    elif profile_mode == "mismatching":
        mismatch_profile = _profile_json(
            capture_id=capture_id,
            body_sha256="0" * 64,
            body_size_bytes=len(_BODY),
            publisher_code=publisher_code,
            source_version=source_version,
        )
        provider_extra_config["statutory_source_catalog"] = mismatch_profile
    provider = ProviderConfigModel.objects.create(
        name=f"origin-snapshot-{capture_id.hex}",
        source_type=PUBLIC_DOCUMENT_SOURCE_TYPE,
        is_active=True,
        priority=50,
        extra_config=provider_extra_config,
    )
    PublisherCatalogModel.objects.create(
        code=publisher_code,
        canonical_name="Synthetic SZSE publisher",
        publisher_class="market_infrastructure",
        website=f"https://{_HOST}/",
        is_active=True,
    )
    revision = StatutorySourceDocumentRevision(
        document_id=f"synthetic-origin-{capture_id.hex}",
        source_version=source_version,
        canonical_url=f"https://{_HOST}/lawrules/{capture_id.hex}.pdf",
        issuer="SZSE",
        title="Synthetic configured source",
        legal_number="SYNTHETIC-ORIGIN-PG",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 11, 15),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 11, 16),
        ),
        body_sha256=body_sha256,
        body_size_bytes=len(_BODY),
    )
    response_at = _database_now() - timedelta(seconds=2)
    response = ProviderDocumentResponseCapture(
        request_id=capture_id,
        attempt=1,
        egress_id=79,
        target_url_sha256=hashlib.sha256(revision.canonical_url.encode("utf-8")).hexdigest(),
        target_host=_HOST,
        body=_BODY,
        body_sha256=body_sha256,
        body_size_bytes=len(_BODY),
        response_completed_at=response_at,
        status_code=200,
        content_type="application/pdf",
        transport=ProviderResponseTransport.EGRESS,
    )
    EgressRequestAuditModel.objects.create(
        request_id=capture_id,
        provider_id=provider.pk,
        dataset_key="statutory_source_documents",
        target_host=_HOST,
        deployment_region=_REGION,
        egress_id=response.egress_id,
        attempt=response.attempt,
        outcome="success",
    )
    from apps.data_center.domain.financial_numeric_source_qualification import (
        FinancialNumericSourceDocumentCaptureReference,
    )

    numeric_reference = FinancialNumericSourceDocumentCaptureReference(
        capture_id=capture_id,
        document_id=revision.document_id,
        issuer=revision.issuer,
        canonical_url=revision.canonical_url,
        body_sha256=body_sha256,
        body_size_bytes=len(_BODY),
        captured_at=response_at,
        content_type="application/pdf",
    )
    FinancialStatutoryNumericPairCaptureRepository(
        revision=revision,
        source_retainer=RetainStatutorySourceDocumentUseCase(
            body_store=body_store,
            document_repository=source_repository,
        ),
        numeric_repository=numeric_repository,
        using=DEFAULT_DB_ALIAS,
    ).append_document_capture(
        provider_id=provider.pk,
        dataset_key="statutory_source_documents",
        deployment_region=_REGION,
        reference=numeric_reference,
        response=response,
    )
    source_reader = DjangoFinancialAvailabilitySourceReader(
        repository=source_repository,
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    known_at = _database_now()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        source_read = source_reader.read_exact_capture(
            issuer=revision.issuer,
            document_id=revision.document_id,
            source_version=revision.source_version,
            capture_id=capture_id,
            known_at=known_at,
        )
    assert source_read is not None and source_read.body == _BODY
    source_reference = source_read.reference
    body_reference = StatutorySourceBodyReference(
        capture_id=capture_id,
        reference=source_reference.body_reference,
        body_sha256=source_reference.body_sha256,
        body_size_bytes=source_reference.body_size_bytes,
    )
    identity = FinancialStatutorySourceIdentity(
        issuer=source_reference.issuer,
        document_id=source_reference.document_id,
        source_version=source_reference.source_version,
        source_revision_sha256=source_reference.source_revision_sha256,
        source_uri=source_reference.canonical_url,
        body_reference=body_reference,
        first_seen_at=source_reference.first_seen_at,
        revision_recorded_at=source_reference.revision_recorded_at,
        capture_observed_at=source_reference.capture_observed_at,
        recorded_at=source_reference.capture_recorded_at,
    )
    stored = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=capture_id)
    return _CapturePair(
        capture_id=capture_id,
        provider=provider,
        profile_json=profile_json,
        numeric_repository=numeric_repository,
        source_reader=source_reader,
        source_repository=source_repository,
        identity=identity,
        source_capture=source_reference,
        body_store=body_store,
        recorded_at=stored.recorded_at,
    )


def test_matching_capture_persists_exact_nonsecret_snapshot_and_current_reader_rechecks(
    tmp_path: Path,
) -> None:
    pair = _capture_pair(tmp_path)
    row = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=pair.capture_id)

    assert row.origin_snapshot is not None
    assert row.origin_snapshot_sha256 is not None
    snapshot = decode_origin_snapshot(row.origin_snapshot, row.origin_snapshot_sha256)
    serialized = str(row.origin_snapshot)
    assert "fixture_secret_marker" not in serialized
    assert snapshot.snapshot_id == pair.capture_id
    assert snapshot.recorded_at == row.recorded_at
    assert (
        snapshot.profile_content_sha256
        == decode_origin_snapshot(
            row.origin_snapshot, row.origin_snapshot_sha256
        ).profile_content_sha256
    )

    reader = DjangoFinancialNumericOriginSnapshotReader(
        capture_repository=pair.numeric_repository,
    )
    known_at = _database_now()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        observation = reader.verify_current(
            pair.identity,
            pair.source_capture,
            known_at=known_at,
        )
    assert observation.origin_snapshot_id == str(pair.capture_id)
    assert observation.origin_snapshot_sha256 == row.origin_snapshot_sha256
    assert observation.numeric_capture_success_audit_count == 1


def test_point_in_time_uses_saved_profile_after_current_catalog_changes(tmp_path: Path) -> None:
    pair = _capture_pair(tmp_path)
    row = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=pair.capture_id)
    assert row.origin_snapshot is not None and row.origin_snapshot_sha256 is not None
    original_hash = row.origin_snapshot_sha256
    cutoff = _database_now()

    changed_profile = dict(pair.profile_json)
    changed_profile["version"] = "fixture-current-version-after-capture"
    changed_extra = dict(pair.provider.extra_config)
    changed_extra["statutory_source_catalog"] = changed_profile
    ProviderConfigModel.objects.filter(pk=pair.provider.pk).update(extra_config=changed_extra)

    reader = DjangoFinancialNumericOriginSnapshotReader(
        capture_repository=pair.numeric_repository,
    )
    historical = reader.verify_point_in_time(
        pair.identity,
        pair.source_capture,
        known_at=cutoff,
    )
    assert historical.origin_snapshot_sha256 == original_hash
    assert historical.profile.version == "test-profile-v1"
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        with pytest.raises(FinancialNumericOriginSnapshotError, match="configuration"):
            reader.verify_current(
                pair.identity,
                pair.source_capture,
                known_at=_database_now(),
            )


@pytest.mark.parametrize("profile_mode", ["missing", "mismatching"])
def test_unconfigured_or_nonmatching_capture_stays_evidence_only(
    tmp_path: Path,
    profile_mode: str,
) -> None:
    pair = _capture_pair(tmp_path, profile_mode=profile_mode)
    row = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=pair.capture_id)

    assert row.origin_snapshot is None
    assert row.origin_snapshot_sha256 is None
    reader = DjangoFinancialNumericOriginSnapshotReader(
        capture_repository=pair.numeric_repository,
    )
    with pytest.raises(FinancialNumericOriginSnapshotError, match="no source-origin snapshot"):
        reader.verify_point_in_time(
            pair.identity,
            pair.source_capture,
            known_at=_database_now(),
        )


def test_snapshot_pair_and_immutable_row_are_database_protected(tmp_path: Path) -> None:
    pair = _capture_pair(tmp_path)
    row = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=pair.capture_id)
    assert row.origin_snapshot is not None
    table = connection.ops.quote_name(FinancialNumericSourceDocumentCaptureModel._meta.db_table)
    pk_column = connection.ops.quote_name(
        FinancialNumericSourceDocumentCaptureModel._meta.pk.column
    )
    snapshot_hash_column = connection.ops.quote_name("origin_snapshot_sha256")
    with pytest.raises(DatabaseError):
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table} SET {snapshot_hash_column} = %s " f"WHERE {pk_column} = %s",
                    ["0" * 64, pair.capture_id],
                )


@pytest.mark.parametrize("missing", ["snapshot", "digest"])
def test_snapshot_pair_constraint_rejects_each_missing_side_on_insert(
    tmp_path: Path,
    missing: str,
) -> None:
    """Exercise the actual CHECK on INSERT, independently of UPDATE triggers."""

    pair = _capture_pair(tmp_path)
    model = FinancialNumericSourceDocumentCaptureModel
    columns = [field.column for field in model._meta.concrete_fields]
    quoted = [connection.ops.quote_name(column) for column in columns]
    selectors: list[str] = []
    params: list[object] = []
    for column, quoted_column in zip(columns, quoted, strict=True):
        if column == "capture_id":
            selectors.append("%s")
            params.append(uuid4())
        elif column == "origin_snapshot":
            selectors.append("NULL" if missing == "snapshot" else "'{}'::jsonb")
        elif column == "origin_snapshot_sha256":
            selectors.append("NULL" if missing == "digest" else "'" + "0" * 64 + "'")
        else:
            selectors.append(quoted_column)
    params.append(pair.capture_id)
    table = connection.ops.quote_name(model._meta.db_table)
    primary_key = connection.ops.quote_name(model._meta.pk.column)
    with pytest.raises(IntegrityError, match="dc_fin_num_origin_snapshot_pair_ck"):
        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {table} ({', '.join(quoted)}) "
                    f"SELECT {', '.join(selectors)} FROM {table} WHERE {primary_key} = %s",
                    params,
                )


@pytest.mark.django_db(transaction=True, available_apps=None)
def test_reverse_migration_refuses_before_discarding_origin_snapshot(tmp_path: Path) -> None:
    """Keep both metadata columns and the applied leaf when origin evidence exists."""

    pair = _capture_pair(tmp_path)
    executor = MigrationExecutor(connection)
    original_targets = executor.loader.graph.leaf_nodes()
    try:
        with pytest.raises(IrreversibleError, match="origin metadata exists"):
            executor.migrate([("data_center", "0117_financial_availability_governance")])
    finally:
        MigrationExecutor(connection).migrate(original_targets)
    row = FinancialNumericSourceDocumentCaptureModel.objects.get(pk=pair.capture_id)
    assert row.origin_snapshot is not None and row.origin_snapshot_sha256 is not None
    assert ("data_center", "0118_financial_numeric_origin_snapshot") in (
        MigrationExecutor(connection).loader.applied_migrations
    )


def test_numeric_append_failure_rolls_back_both_metadata_appends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep actual transport audit while refusing a source-only committed pair."""

    capture_id = uuid4()

    def fail_numeric_append(self: object, **kwargs: object) -> None:
        del self, kwargs
        raise DataValidationError("synthetic numeric retention failure")

    monkeypatch.setattr(
        DjangoFinancialNumericSourceCaptureRepository,
        "append_document_capture",
        fail_numeric_append,
    )
    with pytest.raises(DataValidationError, match="synthetic numeric retention failure"):
        _capture_pair(tmp_path, capture_id=capture_id)
    assert not StatutorySourceDocumentCaptureModel.objects.filter(capture_id=capture_id).exists()
    assert not StatutorySourceDocumentRevisionModel.objects.filter(
        document_id=f"synthetic-origin-{capture_id.hex}"
    ).exists()
    assert not FinancialNumericSourceDocumentCaptureModel.objects.filter(pk=capture_id).exists()
    assert (
        EgressRequestAuditModel.objects.filter(request_id=capture_id, outcome="success").count()
        == 1
    )
    assert (tmp_path / "bodies").exists()
