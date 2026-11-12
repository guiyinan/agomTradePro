"""Typed statutory-source pins for tax assessments, separate from qualification.

The native revision-set digest is stable across repeat captures and bundle
versions. Capture metadata is sealed separately. Neither hash proves official
origin, current qualification, policy activation, or write authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
    _require_digest,
    _require_token,
)

_REVISION_SET_SCHEMA = "statutory-revision-set.v1"


def _canonical_json(payload: dict[str, object]) -> str:
    """Encode a JSON-compatible object with deterministic UTF-8 semantics."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise DeferredDividendTaxValidationError("source payload is not canonical JSON") from error


def _sha256_text(value: str) -> str:
    """Hash one canonical UTF-8 string."""

    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError("source payload must be valid UTF-8") from error
    return sha256(encoded).hexdigest()


def _require_utf8_token(value: object, field_name: str, maximum: int) -> str:
    """Apply the legacy token contract and require UTF-8 encodability."""

    if type(value) is not str:
        raise DeferredDividendTaxValidationError(f"{field_name} must be valid text")
    _require_token(value, field_name, maximum)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(f"{field_name} must be valid UTF-8") from error
    return value


def _instant_text(value: datetime, *, field_name: str) -> str:
    """Normalize an aware instant to UTC without clamping overflow."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise DeferredDividendTaxValidationError(f"{field_name} must be timezone-aware")
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    except (OverflowError, ValueError) as error:
        raise DeferredDividendTaxValidationError(
            f"{field_name} must be representable in UTC"
        ) from error


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    """Require bounded UTF-8 text without surrounding or control whitespace."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DeferredDividendTaxValidationError(f"{field_name} must be bounded non-empty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DeferredDividendTaxValidationError(f"{field_name} must be valid UTF-8") from error
    return value


def _validate_source_url(value: str) -> None:
    """Check canonical HTTPS syntax without asserting publisher authenticity."""

    if any(character.isspace() for character in value) or "#" in value or "\\" in value:
        raise DeferredDividendTaxValidationError("source URL contains a forbidden character")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise DeferredDividendTaxValidationError("source URL is malformed") from error
    if (
        parsed.scheme != "https"
        or host is None
        or not host
        or not host.isascii()
        or host != host.lower()
        or host.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port == 443
        or (port is not None and port < 1)
    ):
        raise DeferredDividendTaxValidationError("source URL must use canonical HTTPS syntax")
    expected_netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        expected_netloc = f"{expected_netloc}:{port}"
    if parsed.netloc != expected_netloc:
        raise DeferredDividendTaxValidationError("source URL must use canonical HTTPS syntax")


class TaxAssessmentSourceDatePrecision(StrEnum):
    """Precision attached to the publisher's native publication/effective date."""

    UNKNOWN = "unknown"
    DATE = "date"
    INSTANT = "instant"


@dataclass(frozen=True, slots=True)
class TaxAssessmentSourceDateEvidence:
    """Preserve source-date precision without inferring or timezone-shifting dates."""

    precision: TaxAssessmentSourceDatePrecision
    date_value: date | None
    instant_value: datetime | None

    def __post_init__(self) -> None:
        """Require exactly the native value shape declared by ``precision``."""

        if type(self.precision) is not TaxAssessmentSourceDatePrecision:
            raise DeferredDividendTaxValidationError("source date precision must be explicit")
        if self.precision is TaxAssessmentSourceDatePrecision.UNKNOWN:
            if self.date_value is not None or self.instant_value is not None:
                raise DeferredDividendTaxValidationError("unknown source date cannot carry a value")
            return
        if self.precision is TaxAssessmentSourceDatePrecision.DATE:
            if type(self.date_value) is not date or self.instant_value is not None:
                raise DeferredDividendTaxValidationError("date precision requires one exact date")
            return
        if self.date_value is not None or type(self.instant_value) is not datetime:
            raise DeferredDividendTaxValidationError("instant precision requires one datetime")
        _instant_text(self.instant_value, field_name="source date instant")


def _source_date_payload(evidence: TaxAssessmentSourceDateEvidence) -> dict[str, str | None]:
    """Serialize native date precision using the Data Center revision contract."""

    evidence.__post_init__()
    if evidence.precision is TaxAssessmentSourceDatePrecision.DATE:
        if evidence.date_value is None:
            raise DeferredDividendTaxValidationError("date-precision source fact is incomplete")
        value = evidence.date_value.isoformat()
    elif evidence.precision is TaxAssessmentSourceDatePrecision.INSTANT:
        if evidence.instant_value is None:
            raise DeferredDividendTaxValidationError("instant-precision source fact is incomplete")
        value = _instant_text(evidence.instant_value, field_name="source date instant")
    else:
        value = None
    return {"precision": evidence.precision.value, "value": value}


@dataclass(frozen=True, slots=True)
class TaxAssessmentStatutorySourceRevision:
    """Complete native source-document facts, independent of capture attempts."""

    document_id: str
    source_version: str
    canonical_url: str
    issuer: str
    title: str
    legal_number: str
    publication_date: TaxAssessmentSourceDateEvidence
    effective_date: TaxAssessmentSourceDateEvidence
    body_sha256: str
    body_size_bytes: int

    def __post_init__(self) -> None:
        """Validate every publisher-native revision fact and exact body seal."""

        for value, name, maximum in (
            (self.document_id, "source.document_id", 240),
            (self.source_version, "source.source_version", 120),
            (self.issuer, "source.issuer", 240),
            (self.title, "source.title", 1000),
            (self.legal_number, "source.legal_number", 240),
            (self.canonical_url, "source.canonical_url", 4096),
        ):
            _required_text(value, field_name=name, maximum=maximum)
        _validate_source_url(self.canonical_url)
        if (
            type(self.publication_date) is not TaxAssessmentSourceDateEvidence
            or type(self.effective_date) is not TaxAssessmentSourceDateEvidence
        ):
            raise DeferredDividendTaxValidationError("source dates must retain precision values")
        self.publication_date.__post_init__()
        self.effective_date.__post_init__()
        _require_digest(self.body_sha256, "source.body_sha256")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise DeferredDividendTaxValidationError("source.body_size_bytes must be positive")

    @property
    def identity_key(self) -> tuple[str, str, str]:
        """Return the exact issuer/document/native-version key."""

        return (self.issuer, self.document_id, self.source_version)

    @property
    def source_revision_sha256(self) -> str:
        """Hash full native revision facts in Data Center's versioned payload shape."""

        payload: dict[str, object] = {
            "document_id": self.document_id,
            "source_version": self.source_version,
            "canonical_url": self.canonical_url,
            "issuer": self.issuer,
            "title": self.title,
            "legal_number": self.legal_number,
            "publication_date": _source_date_payload(self.publication_date),
            "effective_date": _source_date_payload(self.effective_date),
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
        }
        return _sha256_text(_canonical_json(payload))


def _revision_payload(revision: TaxAssessmentStatutorySourceRevision) -> dict[str, object]:
    """Serialize source facts only, omitting UUIDs, clocks, bundle IDs, and locators."""

    return {
        "document_id": revision.document_id,
        "source_version": revision.source_version,
        "canonical_url": revision.canonical_url,
        "issuer": revision.issuer,
        "title": revision.title,
        "legal_number": revision.legal_number,
        "publication_date": _source_date_payload(revision.publication_date),
        "effective_date": _source_date_payload(revision.effective_date),
        "body_sha256": revision.body_sha256,
        "body_size_bytes": revision.body_size_bytes,
    }


@dataclass(frozen=True, slots=True)
class TaxAssessmentSourceCaptureObservation:
    """One retained observation and integrity-checked body reference."""

    capture_id: UUID
    revision: TaxAssessmentStatutorySourceRevision
    captured_at: datetime
    content_type: str
    body_reference: str
    body_sha256: str
    body_size_bytes: int

    def __post_init__(self) -> None:
        """Bind capture UUID, clock, locator, digest, and size to its revision."""

        if type(self.capture_id) is not UUID:
            raise DeferredDividendTaxValidationError("source capture_id must be a UUID")
        if type(self.revision) is not TaxAssessmentStatutorySourceRevision:
            raise DeferredDividendTaxValidationError("capture requires a typed native revision")
        self.revision.__post_init__()
        _instant_text(self.captured_at, field_name="source capture clock")
        _required_text(self.content_type, field_name="source content_type", maximum=200)
        _required_text(self.body_reference, field_name="source body_reference", maximum=1024)
        _require_digest(self.body_sha256, "capture.body_sha256")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise DeferredDividendTaxValidationError("capture.body_size_bytes must be positive")
        if (
            self.body_sha256 != self.revision.body_sha256
            or self.body_size_bytes != self.revision.body_size_bytes
        ):
            raise DeferredDividendTaxValidationError(
                "capture body reference differs from its native source revision"
            )


@dataclass(frozen=True, slots=True)
class TaxAssessmentStatutorySourceBundle:
    """Selected retained captures with semantic revision-set and capture hashes.

    The policy's ``source_identity`` is explicitly
    ``statutory-revision-set.v1:<source_revision_set_sha256>`` and its
    ``source_sha256`` is that digest. Bundle IDs and versions are capture
    selection metadata, not law-content identities.
    """

    bundle_id: str
    version: str
    captures: tuple[TaxAssessmentSourceCaptureObservation, ...]

    def __post_init__(self) -> None:
        """Sort captures and reject duplicate capture or native revision identities."""

        _require_utf8_token(self.bundle_id, "source_bundle.bundle_id", 240)
        _require_utf8_token(self.version, "source_bundle.version", 120)
        if type(self.captures) is not tuple or not self.captures:
            raise DeferredDividendTaxValidationError("source bundle requires selected captures")
        if any(type(item) is not TaxAssessmentSourceCaptureObservation for item in self.captures):
            raise DeferredDividendTaxValidationError("source bundle has an untyped capture")
        if len({item.capture_id for item in self.captures}) != len(self.captures):
            raise DeferredDividendTaxValidationError("source bundle repeats a capture UUID")
        seen: set[tuple[str, str, str]] = set()
        for item in self.captures:
            item.__post_init__()
            key = item.revision.identity_key
            if key in seen:
                raise DeferredDividendTaxValidationError(
                    "source bundle selects one native revision more than once"
                )
            seen.add(key)
        ordered = tuple(sorted(self.captures, key=lambda item: item.revision.identity_key))
        object.__setattr__(self, "captures", ordered)

    @property
    def source_revision_set_sha256(self) -> str:
        """Hash the sorted full native revision set, excluding capture metadata."""

        payload: dict[str, object] = {
            "schema": _REVISION_SET_SCHEMA,
            "revisions": [_revision_payload(item.revision) for item in self.captures],
        }
        return _sha256_text(_canonical_json(payload))

    @property
    def source_revision_set_identity(self) -> str:
        """Return the explicit versioned policy source identity."""

        return f"{_REVISION_SET_SCHEMA}:{self.source_revision_set_sha256}"

    @property
    def source_bundle_sha256(self) -> str:
        """Reproduce Data Center's stored capture-bundle digest for this version."""

        payload: dict[str, object] = {
            "schema": "statutory-source-bundle.v1",
            "bundle_id": self.bundle_id,
            "version": self.version,
            "revisions": [_revision_payload(item.revision) for item in self.captures],
        }
        return _sha256_text(_canonical_json(payload))

    @property
    def capture_manifest_sha256(self) -> str:
        """Hash the exact bundle selection, capture IDs/clocks, and body locations."""

        captures = [
            {
                "capture_id": str(item.capture_id),
                "source_revision_sha256": item.revision.source_revision_sha256,
                "captured_at": _instant_text(item.captured_at, field_name="source capture clock"),
                "content_type": item.content_type,
                "body_reference": {
                    "capture_id": str(item.capture_id),
                    "reference": item.body_reference,
                    "body_sha256": item.body_sha256,
                    "body_size_bytes": item.body_size_bytes,
                },
            }
            for item in self.captures
        ]
        payload: dict[str, object] = {
            "schema": "statutory-source-capture-manifest.v1",
            "bundle_id": self.bundle_id,
            "version": self.version,
            "source_bundle_sha256": self.source_bundle_sha256,
            "captures": captures,
        }
        return _sha256_text(_canonical_json(payload))


__all__ = [
    "TaxAssessmentSourceCaptureObservation",
    "TaxAssessmentSourceDateEvidence",
    "TaxAssessmentSourceDatePrecision",
    "TaxAssessmentStatutorySourceBundle",
    "TaxAssessmentStatutorySourceRevision",
]
