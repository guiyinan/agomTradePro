"""Immutable statutory source revisions, capture observations, and bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    """Require one exact, bounded text value without control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be non-empty bounded text")
    return value


def _require_sha256(value: object, *, field_name: str) -> str:
    """Require a lowercase hexadecimal SHA-256 digest."""

    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


def _validate_utc_representable(value: datetime, *, field_name: str) -> None:
    """Reject aware instants that cannot be normalized to UTC without overflow."""

    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} must be representable in UTC") from error


def _validate_canonical_https_url(value: str) -> None:
    """Validate HTTPS syntax without asserting publisher authenticity."""

    if any(character.isspace() for character in value) or "#" in value or "\\" in value:
        raise ValueError("canonical HTTPS URL must not contain whitespace or a fragment")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("canonical HTTPS URL is malformed") from error

    if (
        parsed.scheme != "https"
        or hostname is None
        or not hostname
        or not hostname.isascii()
        or hostname != hostname.lower()
        or hostname.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port == 443
        or (port is not None and port < 1)
    ):
        raise ValueError("canonical HTTPS URL syntax is invalid")

    expected_netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        expected_netloc = f"{expected_netloc}:{port}"
    if parsed.netloc != expected_netloc:
        raise ValueError("canonical HTTPS URL syntax is invalid")


class StatutorySourceDatePrecision(StrEnum):
    """Precision carried by a source publication or effective-date value."""

    UNKNOWN = "unknown"
    DATE = "date"
    INSTANT = "instant"


@dataclass(frozen=True, slots=True)
class StatutorySourceDateEvidence:
    """Preserve source date precision without guessing a date or timezone."""

    precision: StatutorySourceDatePrecision
    date_value: date | None = None
    instant_value: datetime | None = None

    def __post_init__(self) -> None:
        """Require the value shape to match its explicit source precision."""

        if type(self.precision) is not StatutorySourceDatePrecision:
            raise ValueError("precision must be an exact statutory source date precision")
        if self.precision is StatutorySourceDatePrecision.UNKNOWN:
            if self.date_value is not None or self.instant_value is not None:
                raise ValueError("unknown precision cannot carry a date value")
            return
        if self.precision is StatutorySourceDatePrecision.DATE:
            if type(self.date_value) is not date or self.instant_value is not None:
                raise ValueError("date precision requires exactly one date value")
            return
        if self.date_value is not None or type(self.instant_value) is not datetime:
            raise ValueError("instant precision requires exactly one datetime value")
        if self.instant_value.tzinfo is None or self.instant_value.utcoffset() is None:
            raise ValueError("source instant must be timezone-aware")
        _validate_utc_representable(self.instant_value, field_name="source instant")


@dataclass(frozen=True, slots=True)
class StatutorySourceBodyReference:
    """Opaque storage-issued location bound to one capture ID and exact body."""

    capture_id: UUID
    reference: str
    body_sha256: str
    body_size_bytes: int

    def __post_init__(self) -> None:
        """Validate capture identity, opaque location, digest, and positive size."""

        if type(self.capture_id) is not UUID:
            raise ValueError("capture_id must be a UUID")
        _required_text(self.reference, field_name="body reference", maximum=1024)
        _require_sha256(self.body_sha256, field_name="body_sha256")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise ValueError("body_size_bytes must be a positive integer")

    def verifies(self, body: bytes) -> bool:
        """Return whether bytes match the exact digest and size in this reference."""

        return (
            type(body) is bytes
            and bool(body)
            and len(body) == self.body_size_bytes
            and hashlib.sha256(body).hexdigest() == self.body_sha256
        )


@dataclass(frozen=True, slots=True)
class StatutorySourceDocumentRevision:
    """Publisher-native source revision facts, independent of capture attempts.

    Typed facts and their digest do not authenticate a publisher or activate a
    policy; source qualification remains an application responsibility.
    """

    document_id: str
    source_version: str
    canonical_url: str
    issuer: str
    title: str
    legal_number: str
    publication_date: StatutorySourceDateEvidence
    effective_date: StatutorySourceDateEvidence
    body_sha256: str
    body_size_bytes: int

    def __post_init__(self) -> None:
        """Validate native source facts and bind their body digest and size."""

        for field_name, maximum in (
            ("document_id", 240),
            ("source_version", 120),
            ("issuer", 240),
            ("title", 1000),
            ("legal_number", 240),
        ):
            _required_text(getattr(self, field_name), field_name=field_name, maximum=maximum)
        _required_text(self.canonical_url, field_name="canonical_url", maximum=4096)
        _validate_canonical_https_url(self.canonical_url)
        for field_name in ("publication_date", "effective_date"):
            if type(getattr(self, field_name)) is not StatutorySourceDateEvidence:
                raise ValueError(f"{field_name} must preserve explicit source date precision")
        _require_sha256(self.body_sha256, field_name="body_sha256")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise ValueError("body_size_bytes must be a positive integer")

    @property
    def identity_key(self) -> tuple[str, str, str]:
        """Return issuer, native document ID, and publisher revision identity."""

        return (self.issuer, self.document_id, self.source_version)

    def verifies_source_document(self, body: bytes) -> bool:
        """Return whether exact bytes match this source revision's digest and size."""

        return (
            type(body) is bytes
            and bool(body)
            and len(body) == self.body_size_bytes
            and hashlib.sha256(body).hexdigest() == self.body_sha256
        )

    @property
    def source_revision_sha256(self) -> str:
        """Hash native source facts and content, excluding capture-specific metadata."""

        payload = _revision_payload(self)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RetainedStatutorySourceDocumentCapture:
    """One server-side capture observation of an immutable native source revision."""

    capture_id: UUID
    revision: StatutorySourceDocumentRevision
    captured_at: datetime
    content_type: str
    body_reference: StatutorySourceBodyReference

    def __post_init__(self) -> None:
        """Bind capture clock and storage-issued body reference to the source revision."""

        if type(self.capture_id) is not UUID:
            raise ValueError("capture_id must be a UUID")
        if type(self.revision) is not StatutorySourceDocumentRevision:
            raise ValueError("revision must be an exact statutory source revision")
        if type(self.captured_at) is not datetime:
            raise ValueError("captured_at must be a timezone-aware datetime")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be a timezone-aware datetime")
        _validate_utc_representable(self.captured_at, field_name="captured_at")
        _required_text(self.content_type, field_name="content_type", maximum=200)
        if type(self.body_reference) is not StatutorySourceBodyReference:
            raise ValueError("body_reference must be a storage-issued typed reference")
        if self.body_reference.capture_id != self.capture_id:
            raise ValueError("body reference capture ID does not match capture ID")
        if (
            self.body_reference.body_sha256 != self.revision.body_sha256
            or self.body_reference.body_size_bytes != self.revision.body_size_bytes
        ):
            raise ValueError("body reference digest and size do not match source revision")


@dataclass(frozen=True, slots=True)
class StatutorySourceDocumentBundle:
    """One selected capture per revision with separate semantic and capture hashes.

    Neither hash proves official origin or current policy activation.
    """

    bundle_id: str
    version: str
    captures: tuple[RetainedStatutorySourceDocumentCapture, ...]

    def __post_init__(self) -> None:
        """Sort selected captures and reject duplicate or conflicting native revisions."""

        _required_text(self.bundle_id, field_name="bundle_id", maximum=240)
        _required_text(self.version, field_name="version", maximum=120)
        if type(self.captures) is not tuple or not self.captures:
            raise ValueError("a source bundle must contain at least one capture")
        if any(type(item) is not RetainedStatutorySourceDocumentCapture for item in self.captures):
            raise ValueError("bundle captures must be exact retained captures")
        capture_ids = tuple(item.capture_id for item in self.captures)
        if len(capture_ids) != len(set(capture_ids)):
            raise ValueError("bundle contains a duplicate capture ID")

        seen: dict[tuple[str, str, str], StatutorySourceDocumentRevision] = {}
        for capture in self.captures:
            identity = capture.revision.identity_key
            previous = seen.get(identity)
            if previous is not None:
                if previous != capture.revision:
                    raise ValueError("bundle contains a conflicting source revision")
                raise ValueError("bundle contains a duplicate source revision")
            seen[identity] = capture.revision

        ordered = tuple(sorted(self.captures, key=lambda item: item.revision.identity_key))
        object.__setattr__(self, "captures", ordered)

    @property
    def source_bundle_sha256(self) -> str:
        """Hash native revision facts, excluding capture metadata and storage locations.

        This digest is a consistency identity, not source authenticity proof.
        """

        payload: dict[str, object] = {
            "schema": "statutory-source-bundle.v1",
            "bundle_id": self.bundle_id,
            "version": self.version,
            "revisions": [_revision_payload(item.revision) for item in self.captures],
        }
        return _canonical_sha256(payload)

    @property
    def capture_manifest_sha256(self) -> str:
        """Hash selected capture IDs, clocks, content types, and opaque body references."""

        payload: dict[str, object] = {
            "schema": "statutory-source-capture-manifest.v1",
            "bundle_id": self.bundle_id,
            "version": self.version,
            "source_bundle_sha256": self.source_bundle_sha256,
            "captures": [_capture_payload(item) for item in self.captures],
        }
        return _canonical_sha256(payload)


class StatutorySourceAppendDisposition(StrEnum):
    """Whether an append stored a new capture or returned its exact retry."""

    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class StatutorySourceDocumentAppendResult:
    """Append outcome with the exact source revision and capture records."""

    disposition: StatutorySourceAppendDisposition
    revision: StatutorySourceDocumentRevision
    capture: RetainedStatutorySourceDocumentCapture

    def __post_init__(self) -> None:
        """Require exact typed append disposition, revision, and capture."""

        if type(self.disposition) is not StatutorySourceAppendDisposition:
            raise ValueError("disposition must be a statutory source append disposition")
        if type(self.revision) is not StatutorySourceDocumentRevision:
            raise ValueError("revision must be an exact source revision")
        if type(self.capture) is not RetainedStatutorySourceDocumentCapture:
            raise ValueError("capture must be an exact retained capture")
        if self.capture.revision != self.revision:
            raise ValueError("capture does not bind the result source revision")


@dataclass(frozen=True, slots=True)
class StatutorySourceBundleAppendResult:
    """Append outcome and one exact source bundle record."""

    disposition: StatutorySourceAppendDisposition
    record: StatutorySourceDocumentBundle

    def __post_init__(self) -> None:
        """Require exact result and source bundle types."""

        if type(self.disposition) is not StatutorySourceAppendDisposition:
            raise ValueError("disposition must be a statutory source append disposition")
        if type(self.record) is not StatutorySourceDocumentBundle:
            raise ValueError("record must be an exact statutory source bundle")


def _revision_payload(revision: StatutorySourceDocumentRevision) -> dict[str, object]:
    """Serialize only native source revision facts and exact body identity."""

    return {
        "document_id": revision.document_id,
        "source_version": revision.source_version,
        "canonical_url": revision.canonical_url,
        "issuer": revision.issuer,
        "title": revision.title,
        "legal_number": revision.legal_number,
        "publication_date": _date_payload(revision.publication_date),
        "effective_date": _date_payload(revision.effective_date),
        "body_sha256": revision.body_sha256,
        "body_size_bytes": revision.body_size_bytes,
    }


def _capture_payload(capture: RetainedStatutorySourceDocumentCapture) -> dict[str, object]:
    """Serialize capture provenance separately from semantic source revision identity."""

    return {
        "capture_id": str(capture.capture_id),
        "source_revision_sha256": capture.revision.source_revision_sha256,
        "captured_at": capture.captured_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "content_type": capture.content_type,
        "body_reference": {
            "capture_id": str(capture.body_reference.capture_id),
            "reference": capture.body_reference.reference,
            "body_sha256": capture.body_reference.body_sha256,
            "body_size_bytes": capture.body_reference.body_size_bytes,
        },
    }


def _date_payload(evidence: StatutorySourceDateEvidence) -> dict[str, str | None]:
    """Encode source-clock precision without converting date-only evidence."""

    if evidence.precision is StatutorySourceDatePrecision.DATE:
        if evidence.date_value is None:
            raise ValueError("date precision has no date value")
        value = evidence.date_value.isoformat()
    elif evidence.precision is StatutorySourceDatePrecision.INSTANT:
        if evidence.instant_value is None:
            raise ValueError("instant precision has no datetime value")
        value = evidence.instant_value.astimezone(UTC).isoformat(timespec="microseconds")
    else:
        value = None
    return {"precision": evidence.precision.value, "value": value}


def _canonical_sha256(payload: dict[str, object]) -> str:
    """Hash one canonical JSON object with stable key ordering and no float values."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "RetainedStatutorySourceDocumentCapture",
    "StatutorySourceAppendDisposition",
    "StatutorySourceBodyReference",
    "StatutorySourceBundleAppendResult",
    "StatutorySourceDateEvidence",
    "StatutorySourceDatePrecision",
    "StatutorySourceDocumentAppendResult",
    "StatutorySourceDocumentBundle",
    "StatutorySourceDocumentRevision",
]
