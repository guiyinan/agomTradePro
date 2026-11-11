from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import pytest

from apps.data_center.application.statutory_source_documents import (
    AppendStatutorySourceDocumentBundleUseCase,
    QueryStatutorySourceDocumentBundleUseCase,
    QueryStatutorySourceDocumentUseCase,
    ReadStatutorySourceDocumentBodyUseCase,
    RetainStatutorySourceDocumentUseCase,
    StatutorySourceCaptureConflictError,
    StatutorySourceRevisionConflictError,
)
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceAppendDisposition,
    StatutorySourceBodyReference,
    StatutorySourceBundleAppendResult,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentAppendResult,
    StatutorySourceDocumentBundle,
    StatutorySourceDocumentRevision,
)
from core.exceptions import DataValidationError

BODY = b"<html><body>Synthetic statutory source fixture</body></html>"
OTHER_BODY = b"<html><body>Different synthetic source fixture</body></html>"
_CAPTURE_ID = UUID("00000000-0000-0000-0000-000000000001")
_CAPTURE_ID_2 = UUID("00000000-0000-0000-0000-000000000002")
_CAPTURED_AT = datetime(2026, 11, 12, 3, 4, 5, tzinfo=UTC)


def _date(value: date) -> StatutorySourceDateEvidence:
    return StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.DATE,
        date_value=value,
    )


def _revision(
    *,
    document_id: str = "SYNTHETIC-DOC-001",
    source_version: str = "publisher-revision-1",
    title: str = "Synthetic statutory source fixture",
    body: bytes = BODY,
) -> StatutorySourceDocumentRevision:
    return StatutorySourceDocumentRevision(
        document_id=document_id,
        source_version=source_version,
        canonical_url="https://example.invalid/synthetic/statute",
        issuer="Synthetic publisher fixture",
        title=title,
        legal_number="SYNTHETIC-LAW-001",
        publication_date=_date(date(2001, 2, 3)),
        effective_date=_date(date(2001, 3, 4)),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
    )


def _reference(
    capture_id: UUID = _CAPTURE_ID,
    body: bytes = BODY,
    *,
    reference: str | None = None,
) -> StatutorySourceBodyReference:
    return StatutorySourceBodyReference(
        capture_id=capture_id,
        reference=reference or f"statutory-source-body:///v1/{capture_id}.body",
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
    )


def _capture(
    *,
    revision: StatutorySourceDocumentRevision | None = None,
    capture_id: UUID = _CAPTURE_ID,
    captured_at: datetime = _CAPTURED_AT,
    body: bytes = BODY,
    reference: str | None = None,
    content_type: str = "text/html; charset=utf-8",
) -> RetainedStatutorySourceDocumentCapture:
    selected_revision = revision or _revision(body=body)
    return RetainedStatutorySourceDocumentCapture(
        capture_id=capture_id,
        revision=selected_revision,
        captured_at=captured_at,
        content_type=content_type,
        body_reference=_reference(capture_id, body, reference=reference),
    )


def _bundle(
    captures: tuple[RetainedStatutorySourceDocumentCapture, ...] | None = None,
    *,
    bundle_id: str = "synthetic-source-set",
    version: str = "catalog-revision-1",
) -> StatutorySourceDocumentBundle:
    return StatutorySourceDocumentBundle(
        bundle_id=bundle_id,
        version=version,
        captures=(_capture(),) if captures is None else captures,
    )


def test_source_date_evidence_keeps_date_and_instant_precision_explicit() -> None:
    date_evidence = _date(date(2001, 2, 3))
    instant = datetime(2001, 2, 3, 8, 30, tzinfo=timezone(timedelta(hours=8)))
    instant_evidence = StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.INSTANT,
        instant_value=instant,
    )
    unknown_evidence = StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.UNKNOWN,
    )

    assert date_evidence.date_value == date(2001, 2, 3)
    assert instant_evidence.instant_value == instant
    assert unknown_evidence.date_value is None
    assert unknown_evidence.instant_value is None


def test_source_date_evidence_rejects_precision_value_mismatches() -> None:
    with pytest.raises(ValueError, match="exact statutory source date precision"):
        StatutorySourceDateEvidence(precision="date")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="date precision"):
        StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=datetime(2001, 2, 3, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="unknown precision"):
        StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.UNKNOWN,
            date_value=date(2001, 2, 3),
        )
    with pytest.raises(ValueError, match="exactly one datetime"):
        StatutorySourceDateEvidence(precision=StatutorySourceDatePrecision.INSTANT)
    with pytest.raises(ValueError, match="timezone-aware"):
        StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=datetime(2001, 2, 3, 8, 30),
        )


@pytest.mark.parametrize(
    "instant",
    (
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
        datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-12))),
    ),
)
def test_source_date_evidence_rejects_instants_that_overflow_utc(instant: datetime) -> None:
    with pytest.raises(ValueError, match="representable in UTC"):
        StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=instant,
        )


def test_body_reference_binds_capture_id_exact_hash_and_size() -> None:
    reference = _reference()

    assert reference.verifies(BODY)
    assert not reference.verifies(BODY + b" ")
    assert reference.body_sha256 == sha256(BODY).hexdigest()
    assert reference.body_size_bytes == len(BODY)


def test_body_reference_rejects_bad_capture_digest_size_or_location() -> None:
    with pytest.raises(ValueError, match="capture_id"):
        StatutorySourceBodyReference(
            capture_id="not-a-uuid",  # type: ignore[arg-type]
            reference="opaque://location",
            body_sha256=sha256(BODY).hexdigest(),
            body_size_bytes=len(BODY),
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        StatutorySourceBodyReference(
            capture_id=_CAPTURE_ID,
            reference="opaque://location",
            body_sha256="A" * 64,
            body_size_bytes=1,
        )
    with pytest.raises(ValueError, match="positive integer"):
        StatutorySourceBodyReference(
            capture_id=_CAPTURE_ID,
            reference="opaque://location",
            body_sha256="a" * 64,
            body_size_bytes=True,
        )
    with pytest.raises(ValueError, match="body reference"):
        StatutorySourceBodyReference(
            capture_id=_CAPTURE_ID,
            reference="  ",
            body_sha256="a" * 64,
            body_size_bytes=1,
        )


def test_revision_requires_synthetic_canonical_https_and_exact_body_metadata() -> None:
    revision = _revision()
    assert revision.verifies_source_document(BODY)
    assert not revision.verifies_source_document(OTHER_BODY)
    assert revision.identity_key == (
        "Synthetic publisher fixture",
        "SYNTHETIC-DOC-001",
        "publisher-revision-1",
    )

    for invalid_url in (
        "http://example.invalid/statute",
        "https://user@example.invalid/statute",
        "https://example.invalid:443/statute",
        "https://example.invalid/statute#section",
        "https://EXAMPLE.invalid/statute",
        "https://example.invalid:not-a-port/statute",
    ):
        with pytest.raises(ValueError, match="canonical HTTPS URL"):
            _revision_with_url(revision, invalid_url)

    accepted_unrecognized_host = _revision_with_url(
        revision,
        "https://unrecognized.example.invalid/statute?id=4",
    )
    assert accepted_unrecognized_host.canonical_url.endswith("?id=4")


def _revision_with_url(
    revision: StatutorySourceDocumentRevision,
    canonical_url: str,
) -> StatutorySourceDocumentRevision:
    """Copy one fixture revision while replacing only the source URL."""

    return StatutorySourceDocumentRevision(
        document_id=revision.document_id,
        source_version=revision.source_version,
        canonical_url=canonical_url,
        issuer=revision.issuer,
        title=revision.title,
        legal_number=revision.legal_number,
        publication_date=revision.publication_date,
        effective_date=revision.effective_date,
        body_sha256=revision.body_sha256,
        body_size_bytes=revision.body_size_bytes,
    )


def test_revision_rejects_invalid_text_dates_digest_and_size() -> None:
    revision = _revision()
    with pytest.raises(ValueError, match="document_id"):
        StatutorySourceDocumentRevision(
            document_id=" ",
            source_version=revision.source_version,
            canonical_url=revision.canonical_url,
            issuer=revision.issuer,
            title=revision.title,
            legal_number=revision.legal_number,
            publication_date=revision.publication_date,
            effective_date=revision.effective_date,
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
        )
    with pytest.raises(ValueError, match="explicit source date precision"):
        StatutorySourceDocumentRevision(
            document_id=revision.document_id,
            source_version=revision.source_version,
            canonical_url=revision.canonical_url,
            issuer=revision.issuer,
            title=revision.title,
            legal_number=revision.legal_number,
            publication_date=object(),  # type: ignore[arg-type]
            effective_date=revision.effective_date,
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        StatutorySourceDocumentRevision(
            document_id=revision.document_id,
            source_version=revision.source_version,
            canonical_url=revision.canonical_url,
            issuer=revision.issuer,
            title=revision.title,
            legal_number=revision.legal_number,
            publication_date=revision.publication_date,
            effective_date=revision.effective_date,
            body_sha256="A" * 64,
            body_size_bytes=revision.body_size_bytes,
        )
    with pytest.raises(ValueError, match="positive integer"):
        StatutorySourceDocumentRevision(
            document_id=revision.document_id,
            source_version=revision.source_version,
            canonical_url=revision.canonical_url,
            issuer=revision.issuer,
            title=revision.title,
            legal_number=revision.legal_number,
            publication_date=revision.publication_date,
            effective_date=revision.effective_date,
            body_sha256=revision.body_sha256,
            body_size_bytes=0,
        )


def test_capture_binds_its_server_id_clock_and_storage_issued_reference() -> None:
    revision = _revision()
    capture = _capture(revision=revision)
    assert capture.capture_id == capture.body_reference.capture_id
    assert capture.revision == revision

    with pytest.raises(ValueError, match="capture ID"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID_2,
            revision=revision,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body_reference=_reference(_CAPTURE_ID, BODY),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=revision,
            captured_at=datetime(2026, 11, 12, 3, 4, 5),
            content_type="text/html",
            body_reference=_reference(),
        )
    with pytest.raises(ValueError, match="representable in UTC"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=revision,
            captured_at=datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
            content_type="text/html",
            body_reference=_reference(),
        )
    with pytest.raises(ValueError, match="digest and size"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=revision,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body_reference=_reference(_CAPTURE_ID, OTHER_BODY),
        )


def test_source_bundle_hash_is_stable_across_recaptures_but_manifest_is_not() -> None:
    revision = _revision()
    first_capture = _capture(revision=revision)
    second_capture = _capture(
        revision=revision,
        capture_id=_CAPTURE_ID_2,
        captured_at=_CAPTURED_AT + timedelta(days=1),
        reference="statutory-source-body:///v1/second-capture.body",
    )
    first_bundle = _bundle((first_capture,))
    second_bundle = _bundle((second_capture,))

    assert first_bundle.source_bundle_sha256 == second_bundle.source_bundle_sha256
    assert first_bundle.capture_manifest_sha256 != second_bundle.capture_manifest_sha256
    assert first_bundle.capture_manifest_sha256 == _bundle((first_capture,)).capture_manifest_sha256


def test_source_bundle_hash_changes_for_native_revision_facts_or_body() -> None:
    original = _bundle()
    changed_title = _bundle((_capture(revision=_revision(title="Changed synthetic title")),))
    changed_body = _bundle((_capture(revision=_revision(body=OTHER_BODY), body=OTHER_BODY),))
    changed_version = _bundle(
        (_capture(revision=_revision(source_version="publisher-revision-2")),)
    )

    assert original.source_bundle_sha256 != changed_title.source_bundle_sha256
    assert original.source_bundle_sha256 != changed_body.source_bundle_sha256
    assert original.source_bundle_sha256 != changed_version.source_bundle_sha256


def test_bundle_sorts_captures_and_rejects_duplicate_or_conflicting_revisions() -> None:
    revision_a = _revision(document_id="SYNTHETIC-DOC-A")
    revision_b = _revision(document_id="SYNTHETIC-DOC-B")
    capture_a = _capture(revision=revision_a, capture_id=_CAPTURE_ID)
    capture_b = _capture(revision=revision_b, capture_id=_CAPTURE_ID_2)
    bundle = _bundle((capture_b, capture_a))
    assert tuple(item.revision.document_id for item in bundle.captures) == (
        "SYNTHETIC-DOC-A",
        "SYNTHETIC-DOC-B",
    )

    second_capture_a = _capture(
        revision=revision_a,
        capture_id=UUID("00000000-0000-0000-0000-000000000003"),
    )
    with pytest.raises(ValueError, match="duplicate source revision"):
        _bundle((capture_a, second_capture_a))

    conflicting_revision_a = _revision(document_id="SYNTHETIC-DOC-A", body=OTHER_BODY)
    conflicting_capture = _capture(
        revision=conflicting_revision_a,
        capture_id=UUID("00000000-0000-0000-0000-000000000004"),
        body=OTHER_BODY,
    )
    with pytest.raises(ValueError, match="conflicting source revision"):
        _bundle((capture_a, conflicting_capture))


def test_bundle_rejects_empty_untyped_and_duplicate_capture_ids() -> None:
    with pytest.raises(ValueError, match="at least one"):
        _bundle(())
    with pytest.raises(ValueError, match="exact retained captures"):
        StatutorySourceDocumentBundle(
            bundle_id="synthetic-source-set",
            version="catalog-revision-1",
            captures=(object(),),  # type: ignore[arg-type]
        )
    first = _capture()
    same_id_other_revision = _capture(
        revision=_revision(document_id="SYNTHETIC-DOC-OTHER"),
        capture_id=first.capture_id,
    )
    with pytest.raises(ValueError, match="duplicate capture ID"):
        _bundle((first, same_id_other_revision))


def test_append_result_rejects_untyped_disposition_records() -> None:
    revision = _revision()
    capture = _capture(revision=revision)
    with pytest.raises(ValueError, match="append disposition"):
        StatutorySourceDocumentAppendResult(
            disposition="stored",  # type: ignore[arg-type]
            revision=revision,
            capture=capture,
        )
    with pytest.raises(ValueError, match="exact source revision"):
        StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            revision=object(),  # type: ignore[arg-type]
            capture=capture,
        )
    with pytest.raises(ValueError, match="exact retained capture"):
        StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            revision=revision,
            capture=object(),  # type: ignore[arg-type]
        )


class _MemoryBodyStore:
    """Storage fake that issues capture-scoped references and returns exact bytes."""

    def __init__(self, *, read_override: bytes | None = None) -> None:
        self.read_override = read_override
        self.bodies: dict[UUID, bytes] = {}
        self.references: dict[UUID, StatutorySourceBodyReference] = {}
        self.calls: list[str] = []

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        self.calls.append("store")
        existing = self.bodies.get(capture_id)
        if existing is not None and existing != body:
            raise DataValidationError(
                "Capture ID already stores different bytes.",
                code="STATUTORY_SOURCE_CAPTURE_BODY_CONFLICT",
            )
        self.bodies[capture_id] = body
        reference = self.references.get(capture_id)
        if reference is None:
            reference = _reference(capture_id, body)
            self.references[capture_id] = reference
        return reference

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        self.calls.append("read")
        if self.read_override is not None:
            return self.read_override
        return self.bodies.get(reference.capture_id, b"")


class _MemoryDocumentRepository:
    """Thread-safe fake implementing native-revision and capture-ID CAS semantics."""

    def __init__(self) -> None:
        self.revisions: dict[tuple[str, str, str], StatutorySourceDocumentRevision] = {}
        self.captures: dict[UUID, RetainedStatutorySourceDocumentCapture] = {}
        self.calls: list[str] = []

    def append_capture(
        self,
        revision: StatutorySourceDocumentRevision,
        capture: RetainedStatutorySourceDocumentCapture,
    ) -> StatutorySourceDocumentAppendResult:
        self.calls.append("append")
        if capture.revision != revision:
            raise ValueError("capture does not bind the requested source revision")
        existing_revision = self.revisions.get(revision.identity_key)
        if existing_revision is not None and existing_revision != revision:
            raise StatutorySourceRevisionConflictError()
        existing_capture = self.captures.get(capture.capture_id)
        if existing_capture is not None:
            if existing_capture != capture:
                raise StatutorySourceCaptureConflictError()
            return StatutorySourceDocumentAppendResult(
                disposition=StatutorySourceAppendDisposition.DUPLICATE,
                revision=existing_revision or revision,
                capture=existing_capture,
            )
        self.revisions[revision.identity_key] = existing_revision or revision
        self.captures[capture.capture_id] = capture
        return StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            revision=self.revisions[revision.identity_key],
            capture=capture,
        )

    def get_revision_exact(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
    ) -> StatutorySourceDocumentRevision | None:
        return self.revisions.get((issuer, document_id, source_version))

    def get_capture(self, capture_id: UUID) -> RetainedStatutorySourceDocumentCapture | None:
        return self.captures.get(capture_id)


class _MemoryBundleRepository:
    """Small append/read fake for immutable source bundle use cases."""

    def __init__(self) -> None:
        self.bundles: dict[tuple[str, str], StatutorySourceDocumentBundle] = {}

    def append(
        self,
        bundle: StatutorySourceDocumentBundle,
    ) -> StatutorySourceBundleAppendResult:
        key = (bundle.bundle_id, bundle.version)
        current = self.bundles.get(key)
        if current is not None and current != bundle:
            raise DataValidationError(
                "Bundle identity changed.",
                code="STATUTORY_SOURCE_BUNDLE_CONFLICT",
            )
        self.bundles[key] = current or bundle
        return StatutorySourceBundleAppendResult(
            disposition=(
                StatutorySourceAppendDisposition.DUPLICATE
                if current is not None
                else StatutorySourceAppendDisposition.STORED
            ),
            record=self.bundles[key],
        )

    def get_exact(
        self,
        *,
        bundle_id: str,
        version: str,
    ) -> StatutorySourceDocumentBundle | None:
        return self.bundles.get((bundle_id, version))


def test_retain_verifies_source_body_before_any_storage_write() -> None:
    body_store = _MemoryBodyStore()
    repository = _MemoryDocumentRepository()

    with pytest.raises(DataValidationError) as error:
        RetainStatutorySourceDocumentUseCase(
            body_store=body_store,
            document_repository=repository,
        ).execute(
            revision=_revision(),
            capture_id=_CAPTURE_ID,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body=OTHER_BODY,
        )

    assert error.value.code == "STATUTORY_SOURCE_DOCUMENT_BODY_MISMATCH"
    assert body_store.calls == []
    assert repository.calls == []


@pytest.mark.parametrize(
    "captured_at",
    (
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=14))),
        datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-12))),
    ),
)
def test_retain_rejects_capture_times_that_overflow_before_storage(
    captured_at: datetime,
) -> None:
    body_store = _MemoryBodyStore()
    repository = _MemoryDocumentRepository()

    with pytest.raises(DataValidationError) as error:
        RetainStatutorySourceDocumentUseCase(
            body_store=body_store,
            document_repository=repository,
        ).execute(
            revision=_revision(),
            capture_id=_CAPTURE_ID,
            captured_at=captured_at,
            content_type="text/html",
            body=BODY,
        )

    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_TIME_INVALID"
    assert body_store.calls == []
    assert repository.calls == []


def test_retain_reads_back_exact_bytes_before_appending_metadata() -> None:
    body_store = _MemoryBodyStore()
    repository = _MemoryDocumentRepository()
    result = RetainStatutorySourceDocumentUseCase(
        body_store=body_store,
        document_repository=repository,
    ).execute(
        revision=_revision(),
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html; charset=utf-8",
        body=BODY,
    )

    assert result.disposition is StatutorySourceAppendDisposition.STORED
    assert result.capture.capture_id == _CAPTURE_ID
    assert result.revision == _revision()
    assert body_store.calls == ["store", "read"]
    assert repository.calls == ["append"]


def test_retain_readback_failure_prevents_metadata_append() -> None:
    body_store = _MemoryBodyStore(read_override=BODY + b" altered")
    repository = _MemoryDocumentRepository()

    with pytest.raises(DataValidationError) as error:
        RetainStatutorySourceDocumentUseCase(
            body_store=body_store,
            document_repository=repository,
        ).execute(
            revision=_revision(),
            capture_id=_CAPTURE_ID,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body=BODY,
        )

    assert error.value.code == "STATUTORY_SOURCE_BODY_READBACK_FAILED"
    assert body_store.calls == ["store", "read"]
    assert repository.calls == []


def test_exact_capture_retry_is_idempotent_and_repeated_capture_is_distinct() -> None:
    body_store = _MemoryBodyStore()
    repository = _MemoryDocumentRepository()
    use_case = RetainStatutorySourceDocumentUseCase(
        body_store=body_store,
        document_repository=repository,
    )
    revision = _revision()
    first = use_case.execute(
        revision=revision,
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html",
        body=BODY,
    )
    retry = use_case.execute(
        revision=revision,
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html",
        body=BODY,
    )
    repeat_capture = use_case.execute(
        revision=revision,
        capture_id=_CAPTURE_ID_2,
        captured_at=_CAPTURED_AT + timedelta(days=1),
        content_type="text/html",
        body=BODY,
    )

    assert first.disposition is StatutorySourceAppendDisposition.STORED
    assert retry.disposition is StatutorySourceAppendDisposition.DUPLICATE
    assert repeat_capture.disposition is StatutorySourceAppendDisposition.STORED
    assert len(repository.revisions) == 1
    assert len(repository.captures) == 2


def test_same_native_revision_with_changed_body_or_facts_conflicts() -> None:
    body_store = _MemoryBodyStore()
    repository = _MemoryDocumentRepository()
    use_case = RetainStatutorySourceDocumentUseCase(
        body_store=body_store,
        document_repository=repository,
    )
    original = _revision()
    use_case.execute(
        revision=original,
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html",
        body=BODY,
    )

    with pytest.raises(StatutorySourceRevisionConflictError):
        use_case.execute(
            revision=_revision(body=OTHER_BODY),
            capture_id=UUID("00000000-0000-0000-0000-000000000003"),
            captured_at=_CAPTURED_AT + timedelta(days=1),
            content_type="text/html",
            body=OTHER_BODY,
        )
    with pytest.raises(StatutorySourceRevisionConflictError):
        use_case.execute(
            revision=_revision(title="Changed title"),
            capture_id=UUID("00000000-0000-0000-0000-000000000004"),
            captured_at=_CAPTURED_AT + timedelta(days=2),
            content_type="text/html",
            body=BODY,
        )

    assert len(repository.captures) == 1
    assert repository.revisions[original.identity_key] == original


def test_capture_id_retry_with_changed_capture_facts_conflicts() -> None:
    repository = _MemoryDocumentRepository()
    body_store = _MemoryBodyStore()
    use_case = RetainStatutorySourceDocumentUseCase(
        body_store=body_store,
        document_repository=repository,
    )
    use_case.execute(
        revision=_revision(),
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html",
        body=BODY,
    )

    with pytest.raises(DataValidationError) as error:
        use_case.execute(
            revision=_revision(),
            capture_id=_CAPTURE_ID,
            captured_at=_CAPTURED_AT + timedelta(seconds=1),
            content_type="text/html",
            body=BODY,
        )
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_CONFLICT"
    assert len(repository.captures) == 1


def test_read_body_use_case_verifies_exact_hash_and_size() -> None:
    class _Reader(_MemoryBodyStore):
        def __init__(self, body: bytes) -> None:
            super().__init__(read_override=body)

    good_reader = ReadStatutorySourceDocumentBodyUseCase(_Reader(BODY))
    bad_reader = ReadStatutorySourceDocumentBodyUseCase(_Reader(BODY + b" changed"))
    reference = _reference()

    assert good_reader.execute(reference) == BODY
    with pytest.raises(DataValidationError) as error:
        bad_reader.execute(reference)
    assert error.value.code == "STATUTORY_SOURCE_BODY_INTEGRITY_FAILED"


def test_bundle_append_and_exact_read_preserve_separate_hashes() -> None:
    bundle = _bundle()
    repository = _MemoryBundleRepository()
    result = AppendStatutorySourceDocumentBundleUseCase(repository).execute(bundle)
    query = QueryStatutorySourceDocumentBundleUseCase(repository)

    assert result.record == bundle
    assert query.get_exact(bundle_id=bundle.bundle_id, version=bundle.version) == bundle
    assert query.get_exact(bundle_id=bundle.bundle_id, version="missing") is None
    assert len(bundle.source_bundle_sha256) == 64
    assert len(bundle.capture_manifest_sha256) == 64


def test_revision_accepts_canonical_nondefault_port() -> None:
    revision = _revision_with_url(_revision(), "https://example.invalid:8443/synthetic/statute")
    assert revision.canonical_url == "https://example.invalid:8443/synthetic/statute"


def test_capture_rejects_untyped_identity_revision_clock_and_body_reference() -> None:
    revision = _revision()
    with pytest.raises(ValueError, match="capture_id must be a UUID"):
        RetainedStatutorySourceDocumentCapture(
            capture_id="not-a-uuid",  # type: ignore[arg-type]
            revision=revision,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body_reference=_reference(),
        )
    with pytest.raises(ValueError, match="exact statutory source revision"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=object(),  # type: ignore[arg-type]
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body_reference=_reference(),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=revision,
            captured_at="2026-11-12T03:04:05Z",  # type: ignore[arg-type]
            content_type="text/html",
            body_reference=_reference(),
        )
    with pytest.raises(ValueError, match="storage-issued typed reference"):
        RetainedStatutorySourceDocumentCapture(
            capture_id=_CAPTURE_ID,
            revision=revision,
            captured_at=_CAPTURED_AT,
            content_type="text/html",
            body_reference=object(),  # type: ignore[arg-type]
        )


def test_capture_result_and_bundle_result_reject_mismatched_records() -> None:
    revision = _revision()
    capture = _capture(revision=revision)
    other_revision = _revision(title="Different source facts")
    other_capture = _capture(revision=other_revision)

    with pytest.raises(ValueError, match="does not bind"):
        StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            revision=revision,
            capture=other_capture,
        )

    bundle = _bundle((capture,))
    with pytest.raises(ValueError, match="append disposition"):
        StatutorySourceBundleAppendResult(
            disposition="stored",  # type: ignore[arg-type]
            record=bundle,
        )
    with pytest.raises(ValueError, match="exact statutory source bundle"):
        StatutorySourceBundleAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            record=object(),  # type: ignore[arg-type]
        )


def test_bundle_rejects_invalid_identity_and_capture_clock_offset_is_manifest_only() -> None:
    capture = _capture()
    with pytest.raises(ValueError, match="bundle_id"):
        _bundle((capture,), bundle_id=" ")

    local_capture = _capture(
        revision=capture.revision,
        capture_id=_CAPTURE_ID_2,
        captured_at=_CAPTURED_AT.astimezone(timezone(timedelta(hours=8))),
        content_type="text/html; charset=utf-8",
    )
    local_bundle = _bundle((local_capture,))
    original_bundle = _bundle((capture,))
    assert local_bundle.source_bundle_sha256 == original_bundle.source_bundle_sha256
    assert local_bundle.capture_manifest_sha256 != original_bundle.capture_manifest_sha256


def test_document_query_returns_exact_revision_and_capture() -> None:
    repository = _MemoryDocumentRepository()
    revision = _revision()
    result = RetainStatutorySourceDocumentUseCase(
        body_store=_MemoryBodyStore(),
        document_repository=repository,
    ).execute(
        revision=revision,
        capture_id=_CAPTURE_ID,
        captured_at=_CAPTURED_AT,
        content_type="text/html",
        body=BODY,
    )
    query = QueryStatutorySourceDocumentUseCase(repository)

    assert (
        query.get_revision_exact(
            issuer=revision.issuer,
            document_id=revision.document_id,
            source_version=revision.source_version,
        )
        == revision
    )
    assert query.get_capture(_CAPTURE_ID) == result.capture
    assert query.get_capture(_CAPTURE_ID_2) is None
