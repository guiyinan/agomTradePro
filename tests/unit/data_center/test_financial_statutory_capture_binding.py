"""Pure same-response checks for the v3 statutory and 0116 capture references."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialOfficialSourceIdentity,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_capture_binding import (
    FinancialStatutoryCaptureBindingError,
    financial_numeric_capture_reference_for_statutory,
    verify_financial_statutory_capture_binding,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceBodyReference,
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)

BASE = datetime(2026, 11, 16, 1, 2, 3, tzinfo=UTC)
BODY = b"same synthetic public response retained in both repositories"
BODY_SHA256 = sha256(BODY).hexdigest()


def _source_pair() -> tuple[
    FinancialStatutorySourceIdentity,
    StatutorySourceCaptureReference,
    FinancialNumericSourceDocumentCaptureReference,
]:
    """Build exact reference objects with separate statutory and numeric record clocks."""

    captured_at = BASE + timedelta(seconds=5)
    revision = StatutorySourceDocumentRevision(
        document_id="synthetic-opening-rule-2026",
        source_version="revision-2026-11",
        canonical_url="https://www.szse.cn/lawrules/synthetic-2026.pdf",
        issuer="SZSE",
        title="Synthetic mechanics fixture",
        legal_number="SZSE-SYNTHETIC-2026",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 11, 15),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 11, 16),
        ),
        body_sha256=BODY_SHA256,
        body_size_bytes=len(BODY),
    )
    capture_id = uuid4()
    body_reference = StatutorySourceBodyReference(
        capture_id=capture_id,
        reference=f"statutory-source-body:///v1/{capture_id}.body",
        body_sha256=BODY_SHA256,
        body_size_bytes=len(BODY),
    )
    statutory = StatutorySourceCaptureReference(
        issuer=revision.issuer,
        document_id=revision.document_id,
        source_version=revision.source_version,
        title=revision.title,
        legal_number=revision.legal_number,
        source_revision_sha256=revision.source_revision_sha256,
        capture_id=capture_id,
        capture_content_type="application/pdf",
        body_reference=body_reference.reference,
        canonical_url=revision.canonical_url,
        body_sha256=BODY_SHA256,
        body_size_bytes=len(BODY),
        publication_date=revision.publication_date,
        source_effective_date=revision.effective_date,
        first_seen_at=BASE,
        capture_observed_at=captured_at,
        revision_recorded_at=BASE + timedelta(seconds=6),
        capture_recorded_at=BASE + timedelta(seconds=7),
    )
    identity = FinancialStatutorySourceIdentity(
        issuer=statutory.issuer,
        document_id=statutory.document_id,
        source_version=statutory.source_version,
        source_revision_sha256=statutory.source_revision_sha256,
        source_uri=statutory.canonical_url,
        body_reference=body_reference,
        first_seen_at=statutory.first_seen_at,
        revision_recorded_at=statutory.revision_recorded_at,
        capture_observed_at=statutory.capture_observed_at,
        recorded_at=statutory.capture_recorded_at,
    )
    return identity, statutory, financial_numeric_capture_reference_for_statutory(statutory)


def _verify(
    *,
    identity: object | None = None,
    statutory: StatutorySourceCaptureReference | None = None,
    document: FinancialNumericSourceDocumentCaptureReference | None = None,
    statutory_body: bytes = BODY,
    document_body: bytes = BODY,
    response_at: datetime | None = None,
    numeric_recorded_at: datetime | None = None,
    known_at: datetime | None = None,
    checked_at: datetime | None = None,
    source_checked_at: datetime | None = None,
) -> object:
    """Call the pure verifier with defaults derived from one exact base pair."""

    default_identity, default_statutory, default_document = _source_pair()
    cutoff = known_at or BASE + timedelta(seconds=10)
    check = checked_at or BASE + timedelta(seconds=12)
    source_check = source_checked_at or BASE + timedelta(seconds=11)
    return verify_financial_statutory_capture_binding(
        official_source=identity if identity is not None else default_identity,
        statutory_capture=statutory if statutory is not None else default_statutory,
        statutory_body=statutory_body,
        document_capture=document if document is not None else default_document,
        document_body=document_body,
        document_response_completed_at=response_at or default_document.captured_at,
        document_capture_recorded_at=numeric_recorded_at or BASE + timedelta(seconds=8),
        known_at=cutoff,
        checked_at=check,
        source_checked_at=source_check,
    )


def test_matching_response_produces_reference_only_binding() -> None:
    """One identical UUID, response clock, metadata, and byte string binds."""

    identity, statutory, document = _source_pair()

    result = _verify(identity=identity, statutory=statutory, document=document)

    assert result.official_source == identity
    assert result.statutory_capture == statutory
    assert result.document_capture == document
    assert result.reference_only is True
    assert result.must_not_use_for_decision is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer", "other issuer"),
        ("document_id", "other-document"),
        ("source_version", "other-version"),
        ("source_revision_sha256", "a" * 64),
        ("source_uri", "https://www.szse.cn/other.pdf"),
        ("first_seen_at", BASE - timedelta(seconds=1)),
        ("revision_recorded_at", BASE + timedelta(seconds=5, microseconds=1)),
        ("capture_observed_at", BASE + timedelta(seconds=6)),
        ("recorded_at", BASE + timedelta(seconds=8)),
    ],
)
def test_every_v3_identity_field_must_match_the_native_source(
    field: str,
    value: object,
) -> None:
    """A valid-looking alternate native identity cannot substitute for the bound capture."""

    identity, statutory, document = _source_pair()
    changed = replace(identity, **{field: value})

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(identity=changed, statutory=statutory, document=document)

    assert caught.value.code == "FINANCIAL_STATUTORY_IDENTITY_MISMATCH"


@pytest.mark.parametrize(
    "change",
    [
        "capture_id",
        "body_reference",
        "body_sha256",
        "body_size_bytes",
    ],
)
def test_every_v3_body_reference_field_must_match(
    change: str,
) -> None:
    """Nested storage identity mismatches fail before either body hash is trusted."""

    identity, statutory, document = _source_pair()
    body_reference = identity.body_reference
    if change == "capture_id":
        new_id = uuid4()
        changed_body = replace(
            body_reference,
            capture_id=new_id,
            reference=f"statutory-source-body:///v1/{new_id}.body",
        )
    elif change == "body_reference":
        changed_body = replace(
            body_reference,
            reference=f"statutory-source-body:///v1/{body_reference.capture_id}.other",
        )
    elif change == "body_sha256":
        changed_body = replace(body_reference, body_sha256="b" * 64)
    else:
        changed_body = replace(body_reference, body_size_bytes=len(BODY) + 1)
    changed = replace(identity, body_reference=changed_body)

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(identity=changed, statutory=statutory, document=document)

    assert caught.value.code in {
        "FINANCIAL_STATUTORY_IDENTITY_MISMATCH",
        "FINANCIAL_CAPTURE_IDENTITY_INVALID",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture_id", uuid4()),
        ("document_id", "different-document"),
        ("issuer", "different issuer"),
        ("canonical_url", "https://www.szse.cn/different.pdf"),
        ("body_sha256", "c" * 64),
        ("body_size_bytes", len(BODY) + 1),
        ("captured_at", BASE + timedelta(seconds=6)),
        ("content_type", "application/octet-stream"),
    ],
)
def test_every_numeric_capture_identity_field_must_match(
    field: str,
    value: object,
) -> None:
    """The 0116 capture selector must describe the same HTTP response exactly."""

    identity, statutory, document = _source_pair()
    changed = replace(document, **{field: value})

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(identity=identity, statutory=statutory, document=changed)

    assert caught.value.code == "FINANCIAL_NUMERIC_CAPTURE_IDENTITY_MISMATCH"


def test_old_encrypted_or_untyped_source_branch_is_rejected() -> None:
    """This Statutory Source adapter never claims to verify the legacy encryption branch."""

    _identity, statutory, document = _source_pair()

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        legacy_source = object.__new__(FinancialOfficialSourceIdentity)
        _verify(identity=legacy_source, statutory=statutory, document=document)

    assert caught.value.code == "FINANCIAL_STATUTORY_IDENTITY_UNSUPPORTED"


def test_native_capture_and_document_references_are_exact_types() -> None:
    """Duck-typed references cannot stand in for repository-owned value objects."""

    identity, statutory, document = _source_pair()
    with pytest.raises(FinancialStatutoryCaptureBindingError) as statutory_error:
        _verify(identity=identity, statutory=object(), document=document)
    with pytest.raises(FinancialStatutoryCaptureBindingError) as document_error:
        _verify(identity=identity, statutory=statutory, document=object())

    assert statutory_error.value.code == "FINANCIAL_STATUTORY_CAPTURE_INVALID"
    assert document_error.value.code == "FINANCIAL_NUMERIC_CAPTURE_INVALID"


def test_malformed_v3_identity_is_classified_as_invalid() -> None:
    """A malformed identity is distinct from a valid identity that mismatches the row."""

    identity, statutory, document = _source_pair()
    # Simulate a corrupted object restored from an untrusted persistence layer.
    object.__setattr__(identity, "source_revision_sha256", "not-a-sha256")

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(identity=identity, statutory=statutory, document=document)

    assert caught.value.code == "FINANCIAL_CAPTURE_IDENTITY_INVALID"


@pytest.mark.parametrize(
    "change",
    ["source", "statutory", "numeric", "clock"],
)
def test_constructed_binding_rechecks_its_stored_metadata(change: str) -> None:
    """The result constructor rejects forged detached references and cutoffs."""

    binding = _verify()
    if change == "source":
        altered_source = replace(
            binding.official_source, source_uri="https://www.szse.cn/other.pdf"
        )
        changed = {"official_source": altered_source}
    elif change == "statutory":
        changed = {"statutory_capture": object()}
    elif change == "numeric":
        altered_document = replace(binding.document_capture, content_type="application/pdf; x=1")
        changed = {"document_capture": altered_document}
    else:
        changed = {"known_at": BASE + timedelta(seconds=6)}

    with pytest.raises(ValueError):
        replace(binding, **changed)


@pytest.mark.parametrize(
    ("statutory_body", "document_body"),
    [
        (b"different source body", b"different numeric body"),
        (BODY, b"different numeric body"),
        (b"different source body", BODY),
        (b"", BODY),
        (BODY, b""),
    ],
)
def test_both_repositories_must_return_the_same_actual_bytes(
    statutory_body: bytes,
    document_body: bytes,
) -> None:
    """Equal selectors or asserted hashes cannot replace exact bytes comparison."""

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(statutory_body=statutory_body, document_body=document_body)

    assert caught.value.code in {
        "FINANCIAL_STATUTORY_CAPTURE_BYTES_INVALID",
        "FINANCIAL_NUMERIC_CAPTURE_BYTES_INVALID",
        "FINANCIAL_CAPTURE_BYTES_MISMATCH",
    }


def test_response_clock_must_match_the_statutory_observation() -> None:
    """The 0116 HTTP response completion is the same server-observed instant."""

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(response_at=BASE + timedelta(seconds=4))

    assert caught.value.code == "FINANCIAL_CAPTURE_CLOCK_MISMATCH"


def test_numeric_capture_record_cannot_precede_its_response() -> None:
    """The later catalog row clock must not be fabricated before response completion."""

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        _verify(numeric_recorded_at=BASE + timedelta(seconds=4))

    assert caught.value.code == "FINANCIAL_CAPTURE_CLOCK_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("known_at", BASE + timedelta(seconds=6), "FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID"),
        ("known_at", BASE.replace(tzinfo=None), "FINANCIAL_CAPTURE_CLOCK_INVALID"),
        (
            "known_at",
            BASE.astimezone(timezone(timedelta(hours=8))),
            "FINANCIAL_CAPTURE_CLOCK_INVALID",
        ),
        ("checked_at", BASE + timedelta(seconds=9), "FINANCIAL_CAPTURE_CHECK_CLOCK_INVALID"),
        (
            "source_checked_at",
            BASE + timedelta(seconds=9),
            "FINANCIAL_CAPTURE_CHECK_CLOCK_INVALID",
        ),
        (
            "numeric_recorded_at",
            BASE + timedelta(seconds=11),
            "FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
        ),
    ],
)
def test_explicit_cutoff_and_repository_clocks_are_not_rewritten(
    field: str,
    value: datetime,
    code: str,
) -> None:
    """PIT/current callers must supply UTC cutoffs after every persisted fact."""

    with pytest.raises(FinancialStatutoryCaptureBindingError) as caught:
        if field == "numeric_recorded_at":
            _verify(numeric_recorded_at=value)
        else:
            _verify(**{field: value})

    assert caught.value.code == code


def test_document_selector_is_derived_without_a_synthetic_source_version() -> None:
    """The existing 0116 reference maps only exact shared response fields."""

    _identity, statutory, document = _source_pair()

    assert financial_numeric_capture_reference_for_statutory(statutory) == document


def test_numeric_capture_selector_rejects_untyped_or_malformed_statutory_reference() -> None:
    """The shared-field projection cannot manufacture a valid 0116 selector."""

    _identity, statutory, _document = _source_pair()
    malformed_reference = statutory
    # Exercise revalidation at the adapter boundary after a persisted object is corrupted.
    object.__setattr__(malformed_reference, "body_size_bytes", False)
    with pytest.raises(FinancialStatutoryCaptureBindingError) as untyped:
        financial_numeric_capture_reference_for_statutory(object())
    with pytest.raises(FinancialStatutoryCaptureBindingError) as malformed_error:
        financial_numeric_capture_reference_for_statutory(statutory)

    assert untyped.value.code == "FINANCIAL_STATUTORY_CAPTURE_INVALID"
    assert malformed_error.value.code == "FINANCIAL_STATUTORY_CAPTURE_INVALID"
