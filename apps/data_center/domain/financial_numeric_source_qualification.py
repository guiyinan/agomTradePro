"""Versioned, non-authorizing qualifications for native financial source context.

These values bind a native metric contract to one explicit endpoint, source
applicability, row-context assertion set, retained documentation capture
reference, and effective interval. They do not authenticate an owner approval,
prove that a capture is retained, or qualify a financial fact for D1 or
production. A catalog resolver must independently load and verify those records
at the requested knowledge time before returning a qualification.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeAlias, cast
from urllib.parse import urlsplit
from uuid import UUID

from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract

_QUALIFICATION_SCHEMA = "financial-metric-source-qualification.v1"
_DOCUMENT_REFERENCE_SCHEMA = "financial-metric-source-document-capture-ref.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TEXT_LENGTH = 512
_MAX_INTEGER_BITS = 426

FinancialNumericSourceContextScalar: TypeAlias = str | int | bool


def _required_text(value: object, *, field_name: str, maximum: int = _MAX_TEXT_LENGTH) -> str:
    """Require explicit bounded text without silently cleaning source identities."""

    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(f"{field_name} must be explicit bounded text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be UTF-8 representable") from error
    return value


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    """Require one aware timestamp that can be normalized without overflow."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} must be representable in UTC") from error
    return value


def _utc_datetime(value: object, *, field_name: str) -> datetime:
    """Require an aware UTC timestamp for a server-side document capture."""

    result = _aware_datetime(value, field_name=field_name)
    if result.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")
    return result


def _canonical_https_url(value: str) -> str:
    """Validate one canonical HTTPS source-document address without authenticating it."""

    if any(character.isspace() for character in value) or "#" in value or "\\" in value:
        raise ValueError("canonical_url must not contain whitespace, a fragment, or backslashes")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("canonical_url is malformed") from error
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
        raise ValueError("canonical_url must be an explicit canonical HTTPS address")
    expected_netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        expected_netloc = f"{expected_netloc}:{port}"
    if parsed.netloc != expected_netloc:
        raise ValueError("canonical_url must be an explicit canonical HTTPS address")
    return value


def _scalar_type_name(value: FinancialNumericSourceContextScalar) -> str:
    """Return the wire tag while preserving bool as distinct from integer."""

    if type(value) is str:
        return "string"
    if type(value) is bool:
        return "boolean"
    return "integer"


def _context_scalar(value: object, *, field_name: str) -> FinancialNumericSourceContextScalar:
    """Narrow one exact, non-floating JSON context scalar."""

    if type(value) is str:
        if not value or len(value) > _MAX_TEXT_LENGTH:
            raise ValueError(f"{field_name} must be non-empty bounded text")
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError(f"{field_name} cannot contain control characters")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(f"{field_name} must be UTF-8 representable") from error
        return value
    if type(value) is bool:
        return value
    if type(value) is int and value.bit_length() <= _MAX_INTEGER_BITS:
        return value
    raise TypeError(f"{field_name} must be an exact string, boolean, or bounded integer")


def _mapping(value: object, *, field_name: str, keys: frozenset[str]) -> dict[str, object]:
    """Narrow one exact mapping and reject missing, extra, or non-string keys."""

    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError(f"{field_name} keys must be strings")
        result[key] = item
    if frozenset(result) != keys:
        raise ValueError(f"{field_name} has missing or unsupported fields")
    return result


def _text(payload: Mapping[str, object], key: str, *, field_name: str) -> str:
    """Read exact text from a versioned JSON boundary."""

    return _required_text(payload.get(key), field_name=field_name)


def _parse_datetime(value: object, *, field_name: str) -> datetime:
    """Parse one canonical aware ISO datetime without filling a missing zone."""

    if type(value) is not str:
        raise ValueError(f"{field_name} must be an ISO datetime string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO datetime string") from error
    _aware_datetime(parsed, field_name=field_name)
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must use canonical ISO datetime text")
    return parsed


def _same_wire_value(left: object, right: object) -> bool:
    """Compare JSON-shaped values recursively with exact scalar type identity."""

    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_dict = cast(dict[object, object], left)
        right_dict = cast(dict[object, object], right)
        return left_dict.keys() == right_dict.keys() and all(
            _same_wire_value(left_dict[key], right_dict[key]) for key in left_dict
        )
    if type(left) is list:
        left_list = cast(list[object], left)
        right_list = cast(list[object], right)
        return len(left_list) == len(right_list) and all(
            _same_wire_value(first, second)
            for first, second in zip(left_list, right_list, strict=True)
        )
    return left == right


@dataclass(frozen=True, slots=True)
class FinancialNumericSourceContextRequirement:
    """One caller-supplied exact source-row field/value prerequisite.

    Values are not normalized, converted, or defaulted. In particular, a
    currency label or field condition must be supplied explicitly by the
    catalog input; this type has no currency or metric defaults.
    """

    field_name: str
    expected_value: FinancialNumericSourceContextScalar

    def __post_init__(self) -> None:
        """Reject empty field names and untyped or floating context values."""

        _required_text(self.field_name, field_name="context field", maximum=256)
        _context_scalar(self.expected_value, field_name="context expected value")

    def matches(self, context: Mapping[str, object]) -> bool:
        """Return true only for a present source value with the exact same scalar type."""

        if not isinstance(context, Mapping):
            return False
        if any(type(key) is not str for key in context):
            return False
        actual = context.get(self.field_name)
        return type(actual) is type(self.expected_value) and actual == self.expected_value

    def to_dict(self) -> dict[str, object]:
        """Return exact JSON fields with a type tag that distinguishes bool and int."""

        return {
            "expected_value": self.expected_value,
            "field_name": self.field_name,
            "value_type": _scalar_type_name(self.expected_value),
        }

    @classmethod
    def from_payload(cls, value: object) -> FinancialNumericSourceContextRequirement:
        """Restore one exact typed row-context prerequisite from JSON-shaped data."""

        payload = _mapping(
            value,
            field_name="context requirement",
            keys=frozenset({"field_name", "expected_value", "value_type"}),
        )
        field_name = _text(payload, "field_name", field_name="context field")
        expected = _context_scalar(payload.get("expected_value"), field_name="expected value")
        value_type = _text(payload, "value_type", field_name="context value type")
        if value_type != _scalar_type_name(expected):
            raise ValueError("context value type tag does not match its exact value")
        result = cls(field_name=field_name, expected_value=expected)
        if not _same_wire_value(payload, result.to_dict()):
            raise ValueError("context requirement does not round-trip exactly")
        return result


@dataclass(frozen=True, slots=True)
class FinancialNumericSourceDocumentCaptureReference:
    """Reference one exact captured document body without inventing publisher version.

    ``capture_id`` is a local capture identity, not a publisher-native source
    version. A catalog resolver must independently find this persisted capture
    and verify the retained body and metadata; this value alone is not proof of
    capture existence, official origin, or owner approval.
    """

    capture_id: UUID
    document_id: str
    issuer: str
    canonical_url: str
    body_sha256: str
    body_size_bytes: int
    captured_at: datetime
    content_type: str

    def __post_init__(self) -> None:
        """Bind the reference to explicit URL, capture time, body digest, and size."""

        if type(self.capture_id) is not UUID:
            raise TypeError("capture_id must be a UUID")
        _required_text(self.document_id, field_name="document_id", maximum=240)
        _required_text(self.issuer, field_name="issuer", maximum=240)
        _required_text(self.canonical_url, field_name="canonical_url", maximum=4096)
        _canonical_https_url(self.canonical_url)
        if type(self.body_sha256) is not str or _SHA256.fullmatch(self.body_sha256) is None:
            raise ValueError("body_sha256 must be lowercase SHA-256")
        if (
            type(self.body_size_bytes) is not int
            or self.body_size_bytes <= 0
            or self.body_size_bytes >= sys.maxsize
        ):
            raise ValueError("body_size_bytes must be a positive integer")
        _utc_datetime(self.captured_at, field_name="captured_at")
        _required_text(self.content_type, field_name="content_type", maximum=200)

    def to_dict(self) -> dict[str, object]:
        """Return the exact unversioned capture reference for catalog persistence."""

        return {
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "canonical_url": self.canonical_url,
            "capture_id": str(self.capture_id),
            "captured_at": self.captured_at.isoformat(),
            "content_type": self.content_type,
            "document_id": self.document_id,
            "issuer": self.issuer,
            "schema": _DOCUMENT_REFERENCE_SCHEMA,
        }

    @classmethod
    def from_payload(cls, value: object) -> FinancialNumericSourceDocumentCaptureReference:
        """Restore an exact versioned body reference without treating capture ID as version."""

        payload = _mapping(
            value,
            field_name="document capture reference",
            keys=frozenset(
                {
                    "schema",
                    "capture_id",
                    "document_id",
                    "issuer",
                    "canonical_url",
                    "body_sha256",
                    "body_size_bytes",
                    "captured_at",
                    "content_type",
                }
            ),
        )
        if payload.get("schema") != _DOCUMENT_REFERENCE_SCHEMA:
            raise ValueError("document capture reference schema is unsupported")
        capture_text = _text(payload, "capture_id", field_name="capture_id")
        try:
            capture_id = UUID(capture_text)
        except ValueError as error:
            raise ValueError("capture_id must be a canonical UUID") from error
        if str(capture_id) != capture_text:
            raise ValueError("capture_id must be a canonical UUID")
        size = payload.get("body_size_bytes")
        if type(size) is not int:
            raise ValueError("body_size_bytes must be an integer")
        result = cls(
            capture_id=capture_id,
            document_id=_text(payload, "document_id", field_name="document_id"),
            issuer=_text(payload, "issuer", field_name="issuer"),
            canonical_url=_required_text(
                payload.get("canonical_url"), field_name="canonical_url", maximum=4096
            ),
            body_sha256=_text(payload, "body_sha256", field_name="body_sha256"),
            body_size_bytes=size,
            captured_at=_parse_datetime(payload.get("captured_at"), field_name="captured_at"),
            content_type=_text(payload, "content_type", field_name="content_type"),
        )
        if not _same_wire_value(payload, result.to_dict()):
            raise ValueError("document capture reference does not round-trip exactly")
        return result

    @property
    def identity(self) -> str:
        """Return a digest over the exact local capture reference and raw body identity."""

        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"{_DOCUMENT_REFERENCE_SCHEMA}:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class FinancialNumericSourceQualification:
    """One exact native metric applicability candidate, not an approval event.

    Endpoint and applicability are explicit input, not defaults. The object
    binds them to the complete native metric contract and real-capture
    reference. The production catalog must still verify the approved main
    endpoint, original capture, existing Owner authorization, and database
    record clocks before returning this candidate.
    """

    contract: FinancialMetricSourceContract
    endpoint: str
    source_applicability: str
    document_capture: FinancialNumericSourceDocumentCaptureReference
    context_requirements: tuple[FinancialNumericSourceContextRequirement, ...]
    effective_from: datetime
    effective_until: datetime | None

    def __post_init__(self) -> None:
        """Require complete native identity, exact capture, context, and time scope."""

        if type(self.contract) is not FinancialMetricSourceContract:
            raise TypeError("contract must be a FinancialMetricSourceContract")
        if type(self.document_capture) is not FinancialNumericSourceDocumentCaptureReference:
            raise TypeError("document_capture must be a typed exact capture reference")
        _required_text(self.endpoint, field_name="endpoint", maximum=512)
        if any(character.isspace() for character in self.endpoint):
            raise ValueError("endpoint must preserve one exact whitespace-free identity")
        _required_text(
            self.source_applicability,
            field_name="source_applicability",
            maximum=160,
        )
        if type(self.context_requirements) is not tuple or not self.context_requirements:
            raise ValueError("context_requirements must be a non-empty explicit tuple")
        if any(
            type(item) is not FinancialNumericSourceContextRequirement
            for item in self.context_requirements
        ):
            raise TypeError("context_requirements must contain typed exact requirements")
        names = tuple(item.field_name for item in self.context_requirements)
        if len(names) != len(set(names)):
            raise ValueError("context_requirements cannot repeat a source field")
        effective_from = _aware_datetime(self.effective_from, field_name="effective_from")
        effective_until = self.effective_until
        if effective_until is not None:
            effective_until = _aware_datetime(effective_until, field_name="effective_until")
            if effective_until <= effective_from:
                raise ValueError("effective_until must be later than effective_from")
        if self.document_capture.captured_at > effective_from:
            raise ValueError("effective_from cannot precede the exact document capture")

    def matches_source_context(self, context: Mapping[str, object]) -> bool:
        """Return true only when every explicit source-row prerequisite matches exactly."""

        if not isinstance(context, Mapping) or any(type(key) is not str for key in context):
            return False
        return all(requirement.matches(context) for requirement in self.context_requirements)

    def is_eligible_at(
        self,
        *,
        known_at: datetime,
        source_response_completed_at: datetime,
        recorded_at: datetime | None,
        approved_at: datetime | None,
        revoked_at: datetime | None = None,
    ) -> bool:
        """Check source-time applicability and knowledge clocks without authenticating them.

        ``source_response_completed_at`` must come from independently verified
        retained-response metadata; a financial report period is not a source
        response clock. The effective interval applies to this response time,
        while ``known_at`` separately bounds when the capture and catalog or
        governance records were knowable.
        ``recorded_at`` and ``approved_at`` must come from the existing
        authoritative catalog/governance records. Supplying timestamps here
        does not prove that approval happened; the Infrastructure resolver is
        responsible for authenticating that record before using this check.
        """

        try:
            cutoff = _aware_datetime(known_at, field_name="known_at")
            response_completed = _aware_datetime(
                source_response_completed_at,
                field_name="source_response_completed_at",
            )
            recorded = _aware_datetime(recorded_at, field_name="recorded_at")
            approved = _aware_datetime(approved_at, field_name="approved_at")
            revoked = (
                None if revoked_at is None else _aware_datetime(revoked_at, field_name="revoked_at")
            )
        except (TypeError, ValueError):
            return False
        return (
            self.document_capture.captured_at <= cutoff
            and response_completed <= cutoff
            and self.effective_from <= response_completed
            and (self.effective_until is None or response_completed < self.effective_until)
            and recorded <= cutoff
            and approved <= cutoff
            and (revoked is None or revoked > cutoff)
        )

    def to_dict(self) -> dict[str, object]:
        """Return hash-ready, versioned content with explicit non-authorizing markers."""

        return {
            "context_requirements": [item.to_dict() for item in self.context_requirements],
            "contract": self.contract.to_dict(),
            "contract_identity": self.contract.identity,
            "contract_sha256": self.contract.content_hash,
            "document_capture": self.document_capture.to_dict(),
            "effective_from": self.effective_from.isoformat(),
            "effective_until": (
                self.effective_until.isoformat() if self.effective_until is not None else None
            ),
            "endpoint": self.endpoint,
            "evidence_only": True,
            "must_not_use_for_decision": True,
            "production_ready": False,
            "schema": _QUALIFICATION_SCHEMA,
            "source_applicability": self.source_applicability,
        }

    @classmethod
    def from_payload(cls, value: object) -> FinancialNumericSourceQualification:
        """Restore exact qualification content without adding approval authority."""

        payload = _mapping(
            value,
            field_name="financial source qualification",
            keys=frozenset(
                {
                    "schema",
                    "contract",
                    "contract_identity",
                    "contract_sha256",
                    "endpoint",
                    "source_applicability",
                    "document_capture",
                    "context_requirements",
                    "effective_from",
                    "effective_until",
                    "evidence_only",
                    "production_ready",
                    "must_not_use_for_decision",
                }
            ),
        )
        if payload.get("schema") != _QUALIFICATION_SCHEMA:
            raise ValueError("financial source qualification schema is unsupported")
        if (
            payload.get("evidence_only") is not True
            or payload.get("production_ready") is not False
            or payload.get("must_not_use_for_decision") is not True
        ):
            raise ValueError("financial source qualification markers are invalid")
        raw_requirements = payload.get("context_requirements")
        if type(raw_requirements) is not list:
            raise ValueError("context_requirements must be a JSON array")
        requirements = tuple(
            FinancialNumericSourceContextRequirement.from_payload(item) for item in raw_requirements
        )
        raw_effective_until = payload.get("effective_until")
        effective_until = (
            None
            if raw_effective_until is None
            else _parse_datetime(raw_effective_until, field_name="effective_until")
        )
        contract = FinancialMetricSourceContract.from_payload(payload.get("contract"))
        result = cls(
            contract=contract,
            endpoint=_text(payload, "endpoint", field_name="endpoint"),
            source_applicability=_text(
                payload,
                "source_applicability",
                field_name="source_applicability",
            ),
            document_capture=FinancialNumericSourceDocumentCaptureReference.from_payload(
                payload.get("document_capture")
            ),
            context_requirements=requirements,
            effective_from=_parse_datetime(
                payload.get("effective_from"), field_name="effective_from"
            ),
            effective_until=effective_until,
        )
        if (
            _text(payload, "contract_identity", field_name="contract_identity")
            != result.contract.identity
            or _text(payload, "contract_sha256", field_name="contract_sha256")
            != result.contract.content_hash
            or not _same_wire_value(payload, result.to_dict())
        ):
            raise ValueError("financial source qualification differs from exact reconstruction")
        return result

    @property
    def content_hash(self) -> str:
        """Hash endpoint, applicability, native contract, row context, capture, and clocks."""

        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def identity(self) -> str:
        """Return the versioned exact qualification content identity."""

        return f"{_QUALIFICATION_SCHEMA}:{self.content_hash}"


__all__ = [
    "FinancialMetricSourceContract",
    "FinancialNumericSourceContextRequirement",
    "FinancialNumericSourceContextScalar",
    "FinancialNumericSourceDocumentCaptureReference",
    "FinancialNumericSourceQualification",
]
