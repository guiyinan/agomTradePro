"""Unexecuted native PostgreSQL contract for same-response C2/0116 captures.

The body and metadata here are synthetic mechanics fixtures. The test uses the
real Statutory Source repository, 0116 document-capture repository, successful
egress Audit table, provider row, and retained-byte store; it does not establish
official provenance or DATA-02 eligibility.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction

from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySourceRead,
)
from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
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
from apps.data_center.infrastructure.financial_statutory_numeric_capture_adapter import (
    DjangoFinancialStatutoryNumericCaptureAdapter,
)
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.statutory_source_body_store import (
    StatutorySourceBodyStore,
)
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.data_center",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
    ],
)

_BODY = b"synthetic paired source response for PostgreSQL mechanics"
_URL = "https://www.szse.cn/lawrules/synthetic-current-rules.pdf"
_HOST = "www.szse.cn"
_DATASET = "equity.financial.official-source"
_REGION = "test-region"


@dataclass(frozen=True, slots=True)
class _Pair:
    """One identical synthetic response stored by both existing repositories."""

    adapter: DjangoFinancialStatutoryNumericCaptureAdapter
    identity: FinancialStatutorySourceIdentity
    known_at: datetime
    capture_id: UUID
    source_reference: StatutorySourceCaptureReference


def _database_now() -> datetime:
    """Return PostgreSQL wall time for test bounds and explicit read cutoffs."""

    with connections[DEFAULT_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is datetime and row[0].tzinfo is not None
    return row[0].astimezone(UTC)


def _pair(tmp_path: Path, *, include_numeric_capture: bool = True) -> _Pair:
    """Persist the statutory row first, then the matching 0116 document row."""

    body_store = StatutorySourceBodyStore(tmp_path, max_body_bytes=4096)
    source_repository = DjangoStatutorySourceRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    numeric_repository = DjangoFinancialNumericSourceCaptureRepository(
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    capture_id = uuid4()
    response_at = _database_now() - timedelta(seconds=2)
    body_sha256 = hashlib.sha256(_BODY).hexdigest()
    revision = StatutorySourceDocumentRevision(
        issuer="SZSE",
        document_id=f"synthetic-c2-rules-{capture_id.hex}",
        source_version="test-source-revision-v1",
        canonical_url=_URL,
        title="Synthetic source-capture mechanics",
        legal_number="SYNTHETIC-C2-PG",
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

    if include_numeric_capture:
        provider = ProviderConfigModel.objects.create(
            name=f"paired-source-{capture_id.hex}",
            source_type=PUBLIC_DOCUMENT_SOURCE_TYPE,
            is_active=True,
            priority=50,
        )
        response = ProviderDocumentResponseCapture(
            request_id=capture_id,
            attempt=1,
            egress_id=73,
            target_url_sha256=hashlib.sha256(_URL.encode("utf-8")).hexdigest(),
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
            dataset_key=_DATASET,
            target_host=_HOST,
            deployment_region=_REGION,
            egress_id=response.egress_id,
            attempt=response.attempt,
            outcome="success",
        )

    # Preserve the required lock order for the write-side composition:
    # Statutory append (revision -> capture SHARE ROW EXCLUSIVE), then 0116
    # numeric append (capture -> provider -> successful egress Audit).
    RetainStatutorySourceDocumentUseCase(
        body_store=body_store,
        document_repository=source_repository,
    ).execute(
        revision=revision,
        capture_id=capture_id,
        captured_at=response_at,
        content_type="application/pdf",
        body=_BODY,
    )

    if include_numeric_capture:
        document_reference = FinancialNumericSourceDocumentCaptureReference(
            capture_id=capture_id,
            document_id=revision.document_id,
            issuer=revision.issuer,
            canonical_url=revision.canonical_url,
            body_sha256=body_sha256,
            body_size_bytes=len(_BODY),
            captured_at=response_at,
            content_type="application/pdf",
        )
        numeric_repository.append_document_capture(
            provider_id=provider.pk,
            dataset_key=_DATASET,
            deployment_region=_REGION,
            reference=document_reference,
            response=response,
        )

    statutory_reader = DjangoFinancialAvailabilitySourceReader(
        repository=source_repository,
        body_store=body_store,
        using=DEFAULT_DB_ALIAS,
    )
    known_at = _database_now()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        source_read = statutory_reader.read_exact_capture(
            issuer=revision.issuer,
            document_id=revision.document_id,
            source_version=revision.source_version,
            capture_id=capture_id,
            known_at=known_at,
        )
    assert type(source_read) is FinancialAvailabilitySourceRead
    source_reference = source_read.reference
    body_reference = StatutorySourceBodyReference(
        capture_id=source_reference.capture_id,
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
    adapter = DjangoFinancialStatutoryNumericCaptureAdapter(
        statutory_reader=statutory_reader,
        numeric_capture_repository=numeric_repository,
        using=DEFAULT_DB_ALIAS,
    )
    return _Pair(
        adapter=adapter,
        identity=identity,
        known_at=known_at,
        capture_id=capture_id,
        source_reference=source_reference,
    )


def test_existing_pit_and_current_readers_verify_the_same_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PIT reads use 0116 readback; current reads lock source before 0116 rows."""

    pair = _pair(tmp_path)
    calls: list[str] = []
    source_reader = pair.adapter._statutory_reader
    numeric_repository = pair.adapter._numeric_capture_repository
    original_source_read = source_reader.read_exact_capture
    original_lock = numeric_repository.lock_capture_for_uow
    original_verify = numeric_repository.verify_locked_capture

    def read_source(**kwargs: object) -> FinancialAvailabilitySourceRead | None:
        calls.append("statutory_source_share")
        return original_source_read(**kwargs)

    def lock_numeric(
        reference: FinancialNumericSourceDocumentCaptureReference,
    ) -> object:
        calls.append("numeric_capture_row")
        return original_lock(reference)

    def verify_numeric(locked: object, *, known_at: datetime) -> object:
        calls.append("provider_then_egress_audit")
        return original_verify(locked, known_at=known_at)

    monkeypatch.setattr(source_reader, "read_exact_capture", read_source)
    monkeypatch.setattr(numeric_repository, "lock_capture_for_uow", lock_numeric)
    monkeypatch.setattr(numeric_repository, "verify_locked_capture", verify_numeric)

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        current = pair.adapter.read_current(pair.identity, known_at=_database_now())

    assert calls == [
        "statutory_source_share",
        "numeric_capture_row",
        "provider_then_egress_audit",
    ]
    assert current.document_capture.capture_id == pair.capture_id
    assert current.statutory_capture.capture_id == pair.capture_id
    assert current.reference_only is True

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        pit = pair.adapter.read_as_of(pair.identity, known_at=pair.known_at)
    assert pit.document_capture == current.document_capture
    assert pit.statutory_capture == current.statutory_capture
    assert pit.known_at == pair.known_at


def test_missing_0116_document_capture_blocks_statutory_identity(
    tmp_path: Path,
) -> None:
    """A real statutory body alone cannot satisfy the dual-capture boundary."""

    pair = _pair(tmp_path, include_numeric_capture=False)

    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        with pytest.raises(DataValidationError) as caught:
            pair.adapter.read_as_of(pair.identity, known_at=pair.known_at)

    assert caught.value.code == "FINANCIAL_NUMERIC_CAPTURE_MISSING"


@pytest.fixture(autouse=True)
def _require_owned_native_test_database(
    django_db_use_migrations: bool,
    transactional_db: None,
) -> None:
    """Require actual migrations and an explicitly isolated PostgreSQL TEST.NAME."""

    if connection.vendor != "postgresql" or not django_db_use_migrations:
        pytest.skip("native dual-capture contracts require migrated PostgreSQL")
    assert_native_postgres_test_database()
