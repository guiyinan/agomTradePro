from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from hashlib import sha256
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.domain.statutory_source_documents import (
    RetainedStatutorySourceDocumentCapture as DataCenterCapture,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceBodyReference as DataCenterBodyReference,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence as DataCenterDateEvidence,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDatePrecision as DataCenterDatePrecision,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDocumentBundle as DataCenterBundle,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDocumentRevision as DataCenterRevision,
)
from apps.simulated_trading.domain import corporate_action_tax_source_evidence as source_domain
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_source_evidence import (
    TaxAssessmentSourceCaptureObservation,
    TaxAssessmentSourceDateEvidence,
    TaxAssessmentSourceDatePrecision,
    TaxAssessmentStatutorySourceBundle,
    TaxAssessmentStatutorySourceRevision,
)


def _revision(
    *,
    document_id: str = "synthetic-law-one",
    source_version: str = "synthetic-r1",
    body: bytes = b"synthetic bytes only",
) -> TaxAssessmentStatutorySourceRevision:
    """Return a complete synthetic native-source revision, not legal evidence."""

    return TaxAssessmentStatutorySourceRevision(
        document_id=document_id,
        source_version=source_version,
        canonical_url=f"https://example.invalid/{document_id}",
        issuer="Synthetic unit fixture",
        title=f"Synthetic fixture for {document_id}; not a legal source",
        legal_number=f"NOT-LEGAL-{document_id}",
        publication_date=TaxAssessmentSourceDateEvidence(
            TaxAssessmentSourceDatePrecision.DATE, date(2024, 1, 2), None
        ),
        effective_date=TaxAssessmentSourceDateEvidence(
            TaxAssessmentSourceDatePrecision.INSTANT,
            None,
            datetime(2024, 1, 3, 8, tzinfo=UTC) + timedelta(hours=8),
        ),
        body_sha256=sha256(body).hexdigest(),
        body_size_bytes=len(body),
    )


def _capture(
    revision: TaxAssessmentStatutorySourceRevision,
    capture_id: UUID,
    *,
    captured_at: datetime = datetime(2026, 11, 12, tzinfo=UTC),
) -> TaxAssessmentSourceCaptureObservation:
    """Return one server-observation-shaped fixture for a native source pin."""

    return TaxAssessmentSourceCaptureObservation(
        capture_id=capture_id,
        revision=revision,
        captured_at=captured_at,
        content_type="text/html; charset=utf-8",
        body_reference=f"statutory-source-body:///v1/{capture_id}.body",
        body_sha256=revision.body_sha256,
        body_size_bytes=revision.body_size_bytes,
    )


def _data_center_revision(
    revision: TaxAssessmentStatutorySourceRevision,
) -> DataCenterRevision:
    """Map the local native pin to the public Data Center wire value."""

    publication = revision.publication_date
    effective = revision.effective_date
    publication_precision = DataCenterDatePrecision(publication.precision.value)
    effective_precision = DataCenterDatePrecision(effective.precision.value)
    return DataCenterRevision(
        document_id=revision.document_id,
        source_version=revision.source_version,
        canonical_url=revision.canonical_url,
        issuer=revision.issuer,
        title=revision.title,
        legal_number=revision.legal_number,
        publication_date=DataCenterDateEvidence(
            precision=publication_precision,
            date_value=publication.date_value,
            instant_value=publication.instant_value,
        ),
        effective_date=DataCenterDateEvidence(
            precision=effective_precision,
            date_value=effective.date_value,
            instant_value=effective.instant_value,
        ),
        body_sha256=revision.body_sha256,
        body_size_bytes=revision.body_size_bytes,
    )


def _data_center_bundle(bundle: TaxAssessmentStatutorySourceBundle) -> DataCenterBundle:
    """Map the local pinned captures into the public Data Center contract."""

    captures = tuple(
        DataCenterCapture(
            capture_id=item.capture_id,
            revision=_data_center_revision(item.revision),
            captured_at=item.captured_at,
            content_type=item.content_type,
            body_reference=DataCenterBodyReference(
                capture_id=item.capture_id,
                reference=item.body_reference,
                body_sha256=item.body_sha256,
                body_size_bytes=item.body_size_bytes,
            ),
        )
        for item in bundle.captures
    )
    return DataCenterBundle(bundle.bundle_id, bundle.version, captures)


def test_native_revision_digest_matches_public_data_center_contract() -> None:
    local = _revision()

    assert local.source_revision_sha256 == _data_center_revision(local).source_revision_sha256


def test_capture_hashes_match_public_data_center_bundle_contract() -> None:
    revision = _revision()
    local = TaxAssessmentStatutorySourceBundle(
        "synthetic-bundle",
        "observed-v1",
        (
            _capture(
                revision,
                UUID("11111111-1111-4111-8111-111111111111"),
            ),
        ),
    )
    public = _data_center_bundle(local)

    assert local.source_bundle_sha256 == public.source_bundle_sha256
    assert local.capture_manifest_sha256 == public.capture_manifest_sha256


def test_revision_set_is_sorted_and_stable_across_capture_and_bundle_versions() -> None:
    first_revision = _revision(document_id="synthetic-law-one")
    second_revision = _revision(
        document_id="synthetic-law-two",
        body=b"another synthetic fixture",
    )
    first = TaxAssessmentStatutorySourceBundle(
        "synthetic-capture-set-one",
        "observed-v1",
        (
            _capture(first_revision, UUID("11111111-1111-4111-8111-111111111111")),
            _capture(second_revision, UUID("22222222-2222-4222-8222-222222222222")),
        ),
    )
    second = TaxAssessmentStatutorySourceBundle(
        "synthetic-capture-set-two",
        "observed-v2",
        (
            _capture(
                second_revision,
                UUID("44444444-4444-4444-8444-444444444444"),
                captured_at=datetime(2026, 11, 13, tzinfo=UTC),
            ),
            _capture(
                first_revision,
                UUID("33333333-3333-4333-8333-333333333333"),
                captured_at=datetime(2026, 11, 13, tzinfo=UTC),
            ),
        ),
    )

    assert tuple(item.revision.identity_key for item in first.captures) == tuple(
        item.revision.identity_key for item in second.captures
    )
    assert first.source_revision_set_sha256 == second.source_revision_set_sha256
    assert first.source_revision_set_identity == (
        f"statutory-revision-set.v1:{first.source_revision_set_sha256}"
    )
    assert first.source_bundle_sha256 != second.source_bundle_sha256
    assert first.capture_manifest_sha256 != second.capture_manifest_sha256


def test_source_revision_change_or_missing_revision_changes_complete_set_digest() -> None:
    one = _revision()
    two = _revision(document_id="synthetic-law-two", body=b"other synthetic text")
    full = TaxAssessmentStatutorySourceBundle(
        "synthetic-bundle",
        "set-v1",
        (
            _capture(one, UUID("11111111-1111-4111-8111-111111111111")),
            _capture(two, UUID("22222222-2222-4222-8222-222222222222")),
        ),
    )
    one_only = TaxAssessmentStatutorySourceBundle(
        "synthetic-bundle",
        "set-v1",
        (_capture(one, UUID("33333333-3333-4333-8333-333333333333")),),
    )
    changed = _revision(document_id="synthetic-law-one", body=b"changed synthetic text")
    changed_set = TaxAssessmentStatutorySourceBundle(
        "synthetic-bundle",
        "set-v1",
        (
            _capture(changed, UUID("44444444-4444-4444-8444-444444444444")),
            _capture(two, UUID("55555555-5555-4555-8555-555555555555")),
        ),
    )

    assert full.source_revision_set_sha256 != one_only.source_revision_set_sha256
    assert full.source_revision_set_sha256 != changed_set.source_revision_set_sha256


@pytest.mark.parametrize(
    "precision,date_value,instant_value",
    (
        (TaxAssessmentSourceDatePrecision.UNKNOWN, date(2024, 1, 1), None),
        (TaxAssessmentSourceDatePrecision.DATE, None, None),
        (TaxAssessmentSourceDatePrecision.INSTANT, date(2024, 1, 1), datetime.now(UTC)),
        (TaxAssessmentSourceDatePrecision.INSTANT, None, datetime(2024, 1, 1)),
    ),
)
def test_source_date_precision_rejects_ambiguous_shapes(
    precision: TaxAssessmentSourceDatePrecision,
    date_value: date | None,
    instant_value: datetime | None,
) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxAssessmentSourceDateEvidence(precision, date_value, instant_value)


def test_source_date_instant_rejects_utc_overflow() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxAssessmentSourceDateEvidence(
            TaxAssessmentSourceDatePrecision.INSTANT,
            None,
            datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
        )


def test_source_canonical_helpers_reject_invalid_payload_text_and_clocks() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="canonical JSON"):
        source_domain._canonical_json({"bad": object()})
    with pytest.raises(DeferredDividendTaxValidationError, match="bounded non-empty text"):
        source_domain._required_text(" bad ", field_name="test", maximum=12)
    with pytest.raises(DeferredDividendTaxValidationError, match="valid UTF-8"):
        source_domain._required_text("\ud800", field_name="test", maximum=12)
    with pytest.raises(DeferredDividendTaxValidationError, match="timezone-aware"):
        source_domain._instant_text(datetime(2024, 1, 1), field_name="test")


@pytest.mark.parametrize(
    "url",
    (
        "http://example.invalid/source",
        "https://EXAMPLE.invalid/source",
        "https://user@example.invalid/source",
        "https://example.invalid:443/source",
        "https://example.invalid/source#fragment",
    ),
)
def test_source_revision_rejects_noncanonical_urls(url: str) -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(_revision(), canonical_url=url)


def test_capture_requires_exact_body_seal_and_aware_clock() -> None:
    revision = _revision()
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxAssessmentSourceCaptureObservation(
            capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            revision=revision,
            captured_at=datetime(2026, 11, 12),
            content_type="text/html",
            body_reference="synthetic://body",
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="UUID"):
        TaxAssessmentSourceCaptureObservation(
            capture_id="not-a-uuid",  # type: ignore[arg-type]
            revision=revision,
            captured_at=datetime(2026, 11, 12, tzinfo=UTC),
            content_type="text/html",
            body_reference="synthetic://body",
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="typed native revision"):
        TaxAssessmentSourceCaptureObservation(
            capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            revision=cast(TaxAssessmentStatutorySourceRevision, object()),
            captured_at=datetime(2026, 11, 12, tzinfo=UTC),
            content_type="text/html",
            body_reference="synthetic://body",
            body_sha256=revision.body_sha256,
            body_size_bytes=revision.body_size_bytes,
        )


def test_revision_and_capture_reject_inexact_sizes_and_native_date_types() -> None:
    with pytest.raises(DeferredDividendTaxValidationError, match="body_size_bytes"):
        replace(_revision(), body_size_bytes=True)
    with pytest.raises(DeferredDividendTaxValidationError, match="source dates"):
        replace(_revision(), publication_date=object())
    revision = _revision()
    with pytest.raises(DeferredDividendTaxValidationError, match="body reference differs"):
        replace(_capture(revision, UUID("11111111-1111-4111-8111-111111111111")), body_size_bytes=2)
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxAssessmentSourceCaptureObservation(
            capture_id=UUID("11111111-1111-4111-8111-111111111111"),
            revision=revision,
            captured_at=datetime(2026, 11, 12, tzinfo=UTC),
            content_type="text/html",
            body_reference="synthetic://body",
            body_sha256="0" * 64,
            body_size_bytes=revision.body_size_bytes,
        )


def test_bundle_rejects_duplicate_native_revision_identity() -> None:
    revision = _revision()
    with pytest.raises(DeferredDividendTaxValidationError):
        TaxAssessmentStatutorySourceBundle(
            "synthetic-duplicate",
            "v1",
            (
                _capture(revision, UUID("11111111-1111-4111-8111-111111111111")),
                _capture(revision, UUID("22222222-2222-4222-8222-222222222222")),
            ),
        )


def test_bundle_rejects_untyped_duplicate_capture_and_malformed_identity() -> None:
    revision = _revision()
    first_id = UUID("11111111-1111-4111-8111-111111111111")
    first = _capture(revision, first_id)
    with pytest.raises(DeferredDividendTaxValidationError, match="untyped capture"):
        TaxAssessmentStatutorySourceBundle(
            "synthetic-bundle",
            "v1",
            (cast(TaxAssessmentSourceCaptureObservation, object()),),  # type: ignore[arg-type]
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="capture UUID"):
        TaxAssessmentStatutorySourceBundle(
            "synthetic-bundle",
            "v1",
            (first, replace(first, revision=_revision(source_version="synthetic-r2"))),
        )
    with pytest.raises(DeferredDividendTaxValidationError, match="bundle_id"):
        TaxAssessmentStatutorySourceBundle(" ", "v1", (first,))


def test_bundle_identity_rejects_unencodable_utf8_before_hashing() -> None:
    revision = _revision()
    capture = _capture(revision, UUID("11111111-1111-4111-8111-111111111111"))

    with pytest.raises(DeferredDividendTaxValidationError, match="UTF-8"):
        TaxAssessmentStatutorySourceBundle("\ud800", "v1", (capture,))
    with pytest.raises(DeferredDividendTaxValidationError, match="UTF-8"):
        TaxAssessmentStatutorySourceBundle("synthetic-bundle", "\ud800", (capture,))
