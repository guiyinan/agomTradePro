"""Pure comparison of one statutory capture with one numeric document capture.

This value and its verifier establish only that both existing repositories
returned the same retained response bytes for the explicit knowledge cutoff.
They do not authenticate an Owner event or qualify a financial fact for a
decision or publication.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

from apps.data_center.domain.financial_availability_governance import (
    StatutorySourceCaptureReference,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)


class FinancialStatutoryCaptureBindingError(ValueError):
    """Stable domain failure for an invalid same-response capture binding."""

    def __init__(self, message: str, *, code: str) -> None:
        """Retain an actionable code without exposing retained source bytes."""

        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class FinancialStatutoryCaptureBinding:
    """Reference-only identity for two independently verified views of one body."""

    official_source: FinancialStatutorySourceIdentity
    statutory_capture: StatutorySourceCaptureReference
    document_capture: FinancialNumericSourceDocumentCaptureReference
    document_capture_recorded_at: datetime
    known_at: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Recheck exact references and all clocks represented by this result."""

        if (
            type(self.official_source) is not FinancialStatutorySourceIdentity
            or type(self.statutory_capture) is not StatutorySourceCaptureReference
            or type(self.document_capture) is not FinancialNumericSourceDocumentCaptureReference
        ):
            raise ValueError("capture binding requires exact typed source identities")
        self.official_source.__post_init__()
        self.statutory_capture.__post_init__()
        self.document_capture.__post_init__()
        if not _statutory_identity_matches(self.official_source, self.statutory_capture):
            raise ValueError("capture binding no longer matches its statutory identity")
        expected_document_capture = financial_numeric_capture_reference_for_statutory(
            self.statutory_capture
        )
        if self.document_capture != expected_document_capture:
            raise ValueError("capture binding no longer matches its numeric identity")
        cutoff = _require_utc(self.known_at, "known_at")
        checked = _require_utc(self.checked_at, "checked_at")
        numeric_recorded = _require_utc(
            self.document_capture_recorded_at,
            "document_capture_recorded_at",
        )
        if (
            self.document_capture.captured_at != self.statutory_capture.capture_observed_at
            or numeric_recorded < self.document_capture.captured_at
            or numeric_recorded > cutoff
            or checked < cutoff
            or any(
                _require_utc(clock, "source clock") > cutoff
                for clock in (
                    self.official_source.first_seen_at,
                    self.official_source.revision_recorded_at,
                    self.official_source.capture_observed_at,
                    self.official_source.recorded_at,
                )
            )
        ):
            raise ValueError("capture binding contains an invalid identity or clock")

    @property
    def reference_only(self) -> bool:
        """Require the caller to retain separate Owner, raw-row, and E1 gates."""

        return True

    @property
    def must_not_use_for_decision(self) -> bool:
        """This body-identity comparison is not a financial qualification."""

        return True


def verify_financial_statutory_capture_binding(
    *,
    official_source: object,
    statutory_capture: object,
    statutory_body: bytes,
    document_capture: object,
    document_body: bytes,
    document_response_completed_at: datetime,
    document_capture_recorded_at: datetime,
    known_at: datetime,
    checked_at: datetime,
    source_checked_at: datetime,
) -> FinancialStatutoryCaptureBinding:
    """Require one exact v3 statutory identity and byte-identical numeric capture.

    ``FinancialOfficialSourceIdentity`` (the older encrypted branch) is
    intentionally rejected because the Statutory Source repository cannot
    verify its encryption metadata. The caller supplies both independently
    reread byte bodies; equal hashes alone are not treated as byte equality.
    """

    if type(official_source) is not FinancialStatutorySourceIdentity:
        _fail(
            "FINANCIAL_STATUTORY_IDENTITY_UNSUPPORTED",
            "This adapter requires the exact v3 statutory storage identity.",
        )
    if type(statutory_capture) is not StatutorySourceCaptureReference:
        _fail(
            "FINANCIAL_STATUTORY_CAPTURE_INVALID",
            "The exact Statutory Source capture reference is required.",
        )
    if type(document_capture) is not FinancialNumericSourceDocumentCaptureReference:
        _fail(
            "FINANCIAL_NUMERIC_CAPTURE_INVALID",
            "The exact numeric document capture reference is required.",
        )
    try:
        official_source.__post_init__()
        statutory_capture.__post_init__()
        document_capture.__post_init__()
    except (TypeError, ValueError) as error:
        raise FinancialStatutoryCaptureBindingError(
            "A retained capture identity is malformed.",
            code="FINANCIAL_CAPTURE_IDENTITY_INVALID",
        ) from error

    if not _statutory_identity_matches(official_source, statutory_capture):
        _fail(
            "FINANCIAL_STATUTORY_IDENTITY_MISMATCH",
            "The v3 source identity differs from the exact Statutory Source capture.",
        )

    expected_document_capture = financial_numeric_capture_reference_for_statutory(statutory_capture)
    if document_capture != expected_document_capture:
        _fail(
            "FINANCIAL_NUMERIC_CAPTURE_IDENTITY_MISMATCH",
            "The numeric capture does not bind the same response identity.",
        )

    if type(statutory_body) is not bytes or not statutory_body:
        _fail(
            "FINANCIAL_STATUTORY_CAPTURE_BYTES_INVALID",
            "The Statutory Source repository returned no exact body bytes.",
        )
    if type(document_body) is not bytes or not document_body:
        _fail(
            "FINANCIAL_NUMERIC_CAPTURE_BYTES_INVALID",
            "The numeric capture repository returned no exact body bytes.",
        )
    if (
        statutory_body != document_body
        or len(statutory_body) != statutory_capture.body_size_bytes
        or len(document_body) != document_capture.body_size_bytes
        or hashlib.sha256(statutory_body).hexdigest() != official_source.body_sha256
        or hashlib.sha256(document_body).hexdigest() != document_capture.body_sha256
    ):
        _fail(
            "FINANCIAL_CAPTURE_BYTES_MISMATCH",
            "The retained source repositories did not return the same exact bytes.",
        )

    cutoff = _require_utc(known_at, "known_at")
    checked = _require_utc(checked_at, "checked_at")
    source_checked = _require_utc(source_checked_at, "source_checked_at")
    response_completed = _require_utc(
        document_response_completed_at,
        "document_response_completed_at",
    )
    numeric_recorded = _require_utc(
        document_capture_recorded_at,
        "document_capture_recorded_at",
    )
    if response_completed != statutory_capture.capture_observed_at:
        _fail(
            "FINANCIAL_CAPTURE_CLOCK_MISMATCH",
            "The numeric response completion differs from the statutory observation.",
        )
    if numeric_recorded < response_completed:
        _fail(
            "FINANCIAL_CAPTURE_CLOCK_MISMATCH",
            "The numeric document capture record predates its response.",
        )
    source_clocks = (
        official_source.first_seen_at,
        official_source.revision_recorded_at,
        official_source.capture_observed_at,
        official_source.recorded_at,
    )
    if any(_require_utc(clock, "source clock") > cutoff for clock in source_clocks):
        _fail(
            "FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
            "The v3 statutory identity was not fully known at the requested cutoff.",
        )
    if response_completed > cutoff or numeric_recorded > cutoff:
        _fail(
            "FINANCIAL_CAPTURE_KNOWLEDGE_CUTOFF_INVALID",
            "The numeric response or capture record postdates the requested cutoff.",
        )
    if source_checked < cutoff or checked < max(cutoff, source_checked):
        _fail(
            "FINANCIAL_CAPTURE_CHECK_CLOCK_INVALID",
            "A repository check completed before the requested cutoff.",
        )

    return FinancialStatutoryCaptureBinding(
        official_source=official_source,
        statutory_capture=statutory_capture,
        document_capture=document_capture,
        document_capture_recorded_at=numeric_recorded,
        known_at=cutoff,
        checked_at=checked,
    )


def financial_numeric_capture_reference_for_statutory(
    capture: StatutorySourceCaptureReference,
) -> FinancialNumericSourceDocumentCaptureReference:
    """Map common response metadata without inventing a publisher version.

    The returned value is only a selector for the existing 0116 repository;
    that repository must find the persisted row and independently verify the
    provider, egress Audit, body reference, and exact bytes.
    """

    if type(capture) is not StatutorySourceCaptureReference:
        _fail(
            "FINANCIAL_STATUTORY_CAPTURE_INVALID",
            "The exact Statutory Source capture reference is required.",
        )
    try:
        capture.__post_init__()
    except (TypeError, ValueError) as error:
        raise FinancialStatutoryCaptureBindingError(
            "The Statutory Source capture reference is malformed.",
            code="FINANCIAL_STATUTORY_CAPTURE_INVALID",
        ) from error

    return FinancialNumericSourceDocumentCaptureReference(
        capture_id=capture.capture_id,
        document_id=capture.document_id,
        issuer=capture.issuer,
        canonical_url=capture.canonical_url,
        body_sha256=capture.body_sha256,
        body_size_bytes=capture.body_size_bytes,
        captured_at=capture.capture_observed_at,
        content_type=capture.capture_content_type,
    )


def _statutory_identity_matches(
    identity: FinancialStatutorySourceIdentity,
    capture: StatutorySourceCaptureReference,
) -> bool:
    """Compare all v3 identity fields with the native source reference."""

    body = identity.body_reference
    return (
        identity.issuer == capture.issuer
        and identity.document_id == capture.document_id
        and identity.source_version == capture.source_version
        and identity.source_revision_sha256 == capture.source_revision_sha256
        and identity.source_uri == capture.canonical_url
        and body.capture_id == capture.capture_id
        and body.reference == capture.body_reference
        and body.body_sha256 == capture.body_sha256
        and body.body_size_bytes == capture.body_size_bytes
        and identity.first_seen_at == capture.first_seen_at
        and identity.revision_recorded_at == capture.revision_recorded_at
        and identity.capture_observed_at == capture.capture_observed_at
        and identity.recorded_at == capture.capture_recorded_at
    )


def _require_utc(value: object, name: str) -> datetime:
    """Require a bounded, representable aware UTC timestamp."""

    if type(value) is not datetime or value.tzinfo is None:
        _fail("FINANCIAL_CAPTURE_CLOCK_INVALID", f"{name} must be an aware UTC datetime.")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        _fail("FINANCIAL_CAPTURE_CLOCK_INVALID", f"{name} must be an aware UTC datetime.")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise FinancialStatutoryCaptureBindingError(
            f"{name} is outside the UTC range.",
            code="FINANCIAL_CAPTURE_CLOCK_INVALID",
        ) from error


def _fail(code: str, message: str) -> NoReturn:
    """Raise one stable domain validation code."""

    raise FinancialStatutoryCaptureBindingError(message, code=code)


__all__ = [
    "FinancialStatutoryCaptureBinding",
    "FinancialStatutoryCaptureBindingError",
    "financial_numeric_capture_reference_for_statutory",
    "verify_financial_statutory_capture_binding",
]
