"""Bind governed raw responses to immutable, still-unqualified source retention."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from apps.data_center.application.statutory_source_capture import (
    CaptureStatutorySourceDocumentUseCase,
)
from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.provider_document_response import ProviderDocumentResponseCapture
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture,
    StatutorySourceAppendDisposition,
    StatutorySourceBodyReference,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentAppendResult,
    StatutorySourceDocumentRevision,
)
from core.exceptions import DataFetchError, DataValidationError

BODY = b"<html>Explicit synthetic source fixture, not a legal policy.</html>"
URL = "https://example.invalid/fixture/native-101"
COMPLETED = datetime(2026, 11, 1, 3, 4, 5, tzinfo=UTC)
MIME = frozenset({"text/html"})


class MemoryBodyStore:
    def __init__(self) -> None:
        self.bodies: dict[UUID, bytes] = {}

    def store(self, capture_id: UUID, body: bytes) -> StatutorySourceBodyReference:
        self.bodies[capture_id] = body
        return StatutorySourceBodyReference(
            capture_id=capture_id,
            reference=f"statutory-source-body:///v1/{capture_id}.body",
            body_sha256=sha256(body).hexdigest(),
            body_size_bytes=len(body),
        )

    def read(self, reference: StatutorySourceBodyReference) -> bytes:
        return self.bodies[reference.capture_id]


class MemoryMetadata:
    def __init__(self) -> None:
        self.captures: list[RetainedStatutorySourceDocumentCapture] = []

    def append_capture(
        self,
        revision: StatutorySourceDocumentRevision,
        capture: RetainedStatutorySourceDocumentCapture,
    ) -> StatutorySourceDocumentAppendResult:
        self.captures.append(capture)
        return StatutorySourceDocumentAppendResult(
            disposition=StatutorySourceAppendDisposition.STORED,
            revision=revision,
            capture=capture,
        )

    def get_revision_exact(
        self, *, issuer: str, document_id: str, source_version: str
    ) -> StatutorySourceDocumentRevision | None:
        return None

    def get_capture(self, capture_id: UUID) -> RetainedStatutorySourceDocumentCapture | None:
        return None


class Fetch:
    def __init__(self, capture: ProviderDocumentResponseCapture) -> None:
        self.capture = capture
        self.calls: list[tuple[EgressRequestContext, int, frozenset[str], int]] = []

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        self.calls.append((context, max_bytes, allowed_media_types, max_attempts))
        return self.capture


def revision() -> StatutorySourceDocumentRevision:
    return StatutorySourceDocumentRevision(
        issuer="Synthetic issuer",
        document_id="fixture-101",
        source_version="fixture-native-edition",
        canonical_url=URL,
        title="Synthetic source only",
        legal_number="fixture-101",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE, date_value=date(2015, 9, 7)
        ),
        effective_date=StatutorySourceDateEvidence(precision=StatutorySourceDatePrecision.UNKNOWN),
        body_sha256=sha256(BODY).hexdigest(),
        body_size_bytes=len(BODY),
    )


def response() -> ProviderDocumentResponseCapture:
    return ProviderDocumentResponseCapture(
        request_id=uuid4(),
        attempt=1,
        egress_id=None,
        target_url_sha256=sha256(URL.encode()).hexdigest(),
        target_host="example.invalid",
        body=BODY,
        body_sha256=sha256(BODY).hexdigest(),
        body_size_bytes=len(BODY),
        response_completed_at=COMPLETED,
        status_code=200,
        content_type="text/html; charset=utf-8",
        transport=ProviderResponseTransport.EGRESS,
    )


def pipeline(
    capture: ProviderDocumentResponseCapture,
) -> tuple[CaptureStatutorySourceDocumentUseCase, Fetch, MemoryBodyStore, MemoryMetadata]:
    store, metadata, fetch = MemoryBodyStore(), MemoryMetadata(), Fetch(capture)
    use_case = CaptureStatutorySourceDocumentUseCase(
        retainer=RetainStatutorySourceDocumentUseCase(
            body_store=store, document_repository=metadata
        ),
        document_fetch=fetch,
        provider_id=7,
        dataset_key="synthetic_statutory_documents",
        deployment_region="test-region",
    )
    return use_case, fetch, store, metadata


def test_capture_retains_response_uuid_completion_and_exact_revision() -> None:
    captured = response()
    use_case, fetch, store, metadata = pipeline(captured)
    expected = revision()
    result = use_case.execute(revision=expected, max_bytes=4096, allowed_media_types=MIME)
    assert result.revision == expected
    assert result.capture.capture_id == captured.request_id
    assert result.capture.captured_at == COMPLETED
    assert result.capture.content_type == captured.content_type
    assert result.capture.revision.publication_date.date_value == date(2015, 9, 7)
    assert result.capture.revision.effective_date.precision is StatutorySourceDatePrecision.UNKNOWN
    assert store.bodies == {captured.request_id: BODY}
    assert metadata.captures == [result.capture]
    context, maximum, media, attempts = fetch.calls[0]
    assert context == EgressRequestContext(7, "synthetic_statutory_documents", URL, "test-region")
    assert (maximum, media, attempts) == (4096, MIME, 2)


@pytest.mark.parametrize(
    "change",
    [
        {"target_url_sha256": sha256(b"https://other.invalid/").hexdigest()},
        {"target_host": "other.invalid"},
        {"transport": ProviderResponseTransport.DIRECT},
        {"attempt": 3},
        {"content_type": "application/pdf"},
        {"content_type": "text/html; x=" + "a" * 200},
        {
            "body": b"changed original bytes",
            "body_sha256": sha256(b"changed original bytes").hexdigest(),
            "body_size_bytes": len(b"changed original bytes"),
        },
    ],
)
def test_mismatched_capture_never_writes_body_or_metadata(change: dict[str, object]) -> None:
    use_case, fetch, store, metadata = pipeline(replace(response(), **change))
    with pytest.raises(DataValidationError):
        use_case.execute(revision=revision(), max_bytes=4096, allowed_media_types=MIME)
    assert len(fetch.calls) == 1
    assert not store.bodies and not metadata.captures


@pytest.mark.parametrize("maximum", [0, -1, True, len(BODY) - 1])
def test_invalid_or_insufficient_limit_rejected_before_network(maximum: int) -> None:
    use_case, fetch, store, metadata = pipeline(response())
    with pytest.raises(DataValidationError):
        use_case.execute(revision=revision(), max_bytes=maximum, allowed_media_types=MIME)
    assert not fetch.calls and not store.bodies and not metadata.captures


@pytest.mark.parametrize(
    "media", [frozenset(), frozenset({"text/*"}), frozenset({"text/html;x=y"})]
)
def test_invalid_mime_allowlist_rejected_before_network(media: frozenset[str]) -> None:
    use_case, fetch, store, metadata = pipeline(response())
    with pytest.raises(DataValidationError):
        use_case.execute(revision=revision(), max_bytes=4096, allowed_media_types=media)
    assert not fetch.calls and not store.bodies and not metadata.captures


def test_single_attempt_bound_is_preserved() -> None:
    use_case, fetch, store, metadata = pipeline(replace(response(), attempt=2))
    with pytest.raises(DataValidationError):
        use_case.execute(
            revision=revision(), max_bytes=4096, allowed_media_types=MIME, max_attempts=1
        )
    assert fetch.calls[0][3] == 1
    assert not store.bodies and not metadata.captures


def test_provider_failure_propagates_without_storage() -> None:
    store, metadata = MemoryBodyStore(), MemoryMetadata()

    def blocked(
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        raise DataFetchError("Synthetic blocked transport", code="EGRESS_SYNTHETIC_BLOCK")

    use_case = CaptureStatutorySourceDocumentUseCase(
        retainer=RetainStatutorySourceDocumentUseCase(
            body_store=store, document_repository=metadata
        ),
        document_fetch=blocked,
        provider_id=7,
        dataset_key="synthetic_statutory_documents",
        deployment_region="test-region",
    )
    with pytest.raises(DataFetchError, match="Synthetic blocked transport"):
        use_case.execute(revision=revision(), max_bytes=4096, allowed_media_types=MIME)
    assert not store.bodies and not metadata.captures
