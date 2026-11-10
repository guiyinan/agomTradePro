"""Typed source facts for official SSE and SZSE public disclosures."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias
from urllib.parse import urlsplit

SourceEventClock: TypeAlias = date | datetime


@dataclass(frozen=True, slots=True)
class SzseDistributionTerms:
    """Source-exact distribution terms; absence blocks economic posting."""

    record_date: date
    ex_date: date
    payment_date: date | None
    cash_per_ten: Decimal | None
    shares_per_ten: Decimal | None
    tax_treatment: str | None


class SecurityDisclosureExchange(StrEnum):
    """Supported security exchanges for this source-only contract."""

    SSE = "SSE"
    SZSE = "SZSE"


class SecurityDisclosureSource(StrEnum):
    """Official disclosure source identity bound to one exchange."""

    SSE_OFFICIAL = "sse_official"
    SZSE_OFFICIAL = "szse_official"

    @property
    def exchange(self) -> SecurityDisclosureExchange:
        """Return the exchange whose official disclosure source this names."""

        if self is SecurityDisclosureSource.SSE_OFFICIAL:
            return SecurityDisclosureExchange.SSE
        return SecurityDisclosureExchange.SZSE


class SecurityDisclosureEventType(StrEnum):
    """Normalized disclosure category; unknown source categories stay explicit."""

    FINANCIAL_REPORT = "financial_report"
    PERFORMANCE_FORECAST = "performance_forecast"
    RISK_STATUS = "risk_status"
    SUSPENSION = "suspension"
    RESUMPTION = "resumption"
    CASH_DIVIDEND = "cash_dividend"
    STOCK_DIVIDEND = "stock_dividend"
    RIGHTS_ISSUE = "rights_issue"
    SHARE_UNLOCK = "share_unlock"
    REDUCTION = "reduction"
    REPURCHASE = "repurchase"
    OTHER = "other"
    UNKNOWN = "unknown"


_CANONICAL_SECURITY_CODE = re.compile(r"^[0-9]{6}\.(SH|SZ)$")
_SOURCE_SECURITY_CODE = re.compile(r"^[0-9]{6}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    """Require one exact, trimmed, bounded source token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{field_name} must be non-empty bounded text")
    return value


def _require_source_clock(value: object, *, field_name: str, optional: bool) -> None:
    """Preserve date precision and reject naive or malformed source timestamps."""

    if value is None and optional:
        return
    if type(value) is date:
        return
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must be timezone-aware")
        return
    raise ValueError(f"{field_name} must preserve a source date or datetime")


def _clock_payload(value: SourceEventClock | None) -> dict[str, str] | None:
    """Serialize a source clock without expanding date-only evidence."""

    if value is None:
        return None
    if type(value) is date:
        return {"precision": "date", "value": value.isoformat()}
    if type(value) is datetime:
        return {
            "precision": "datetime",
            "value": value.astimezone(UTC).isoformat(timespec="microseconds"),
        }
    raise ValueError("source clock has an unsupported runtime type")


def _validate_source_url(value: str, *, source: SecurityDisclosureSource) -> None:
    """Require HTTPS on the selected exchange's official web domain."""

    parsed = urlsplit(value)
    try:
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("source_url is malformed") from error
    official_domain = "sse.com.cn" if source is SecurityDisclosureSource.SSE_OFFICIAL else "szse.cn"
    if (
        parsed.scheme != "https"
        or not host
        or not (host == official_domain or host.endswith(f".{official_domain}"))
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("source_url must use the selected exchange's official HTTPS domain")


@dataclass(frozen=True, slots=True)
class SecurityDisclosureEvent:
    """One immutable, source-bound disclosure for an exact security revision."""

    source: SecurityDisclosureSource
    exchange: SecurityDisclosureExchange
    asset_code: str
    source_security_code: str
    source_event_id: str
    source_revision_id: str
    raw_event_type: str
    event_type: SecurityDisclosureEventType
    source_url: str
    source_body_sha256: str
    announced_at: SourceEventClock | None
    source_available_at: SourceEventClock | None
    first_seen_at: datetime
    effective_at: SourceEventClock | None = None
    supersedes_source_event_id: str | None = None
    supersedes_source_revision_id: str | None = None

    def __post_init__(self) -> None:
        """Reject missing source identity, evidence, clock, and security bindings."""

        if type(self.source) is not SecurityDisclosureSource:
            raise ValueError("source must be an official exchange disclosure source")
        if type(self.exchange) is not SecurityDisclosureExchange:
            raise ValueError("exchange must be an exact supported exchange")
        if self.source.exchange is not self.exchange:
            raise ValueError("source and exchange identity disagree")
        if type(self.event_type) is not SecurityDisclosureEventType:
            raise ValueError("event_type must use the disclosure event taxonomy")

        asset_code = _required_text(self.asset_code, field_name="asset_code", maximum=20)
        source_code = _required_text(
            self.source_security_code,
            field_name="source_security_code",
            maximum=40,
        )
        _required_text(self.source_event_id, field_name="source_event_id", maximum=200)
        _required_text(self.source_revision_id, field_name="source_revision_id", maximum=200)
        _required_text(self.raw_event_type, field_name="raw_event_type", maximum=120)
        source_url = _required_text(self.source_url, field_name="source_url", maximum=2048)
        if type(self.source_body_sha256) is not str or not _SHA256.fullmatch(
            self.source_body_sha256
        ):
            raise ValueError("source_body_sha256 must be lowercase SHA-256")
        _validate_source_url(source_url, source=self.source)

        expected_suffix = ".SH" if self.exchange is SecurityDisclosureExchange.SSE else ".SZ"
        if (
            not _CANONICAL_SECURITY_CODE.fullmatch(asset_code)
            or not asset_code.endswith(expected_suffix)
            or not _SOURCE_SECURITY_CODE.fullmatch(source_code)
            or source_code != asset_code[:6]
        ):
            raise ValueError("source security identity does not match the canonical exchange code")

        _require_source_clock(self.announced_at, field_name="announced_at", optional=True)
        _require_source_clock(
            self.source_available_at,
            field_name="source_available_at",
            optional=True,
        )
        _require_source_clock(self.effective_at, field_name="effective_at", optional=True)
        if type(self.first_seen_at) is not datetime:
            raise ValueError("first_seen_at must be a timezone-aware datetime")
        if self.first_seen_at.tzinfo is None or self.first_seen_at.utcoffset() is None:
            raise ValueError("first_seen_at must be a timezone-aware datetime")
        if type(self.announced_at) is datetime and self.announced_at > self.first_seen_at:
            raise ValueError("announced_at cannot follow first_seen_at")
        if (
            type(self.source_available_at) is datetime
            and self.source_available_at > self.first_seen_at
        ):
            raise ValueError("source_available_at cannot follow first_seen_at")

        superseded_event = self.supersedes_source_event_id
        superseded_revision = self.supersedes_source_revision_id
        if (superseded_event is None) != (superseded_revision is None):
            raise ValueError("supersession requires both source event and revision IDs")
        if superseded_event is not None and superseded_revision is not None:
            _required_text(
                superseded_event,
                field_name="supersedes_source_event_id",
                maximum=200,
            )
            _required_text(
                superseded_revision,
                field_name="supersedes_source_revision_id",
                maximum=200,
            )
            if (superseded_event, superseded_revision) == self.identity_key[3:]:
                raise ValueError("a disclosure revision cannot supersede itself")

    @property
    def identity_key(self) -> tuple[str, str, str, str, str]:
        """Return exact source, exchange, security, native event, and revision identity."""

        return (
            self.source.value,
            self.exchange.value,
            self.asset_code,
            self.source_event_id,
            self.source_revision_id,
        )

    @property
    def available_at(self) -> datetime:
        """Return the conservative PIT bound established by first observation."""

        return self.first_seen_at

    @classmethod
    def from_source_document(
        cls,
        *,
        source: SecurityDisclosureSource,
        exchange: SecurityDisclosureExchange,
        asset_code: str,
        source_security_code: str,
        source_event_id: str,
        source_revision_id: str,
        raw_event_type: str,
        event_type: SecurityDisclosureEventType,
        source_url: str,
        source_document_body: bytes,
        first_seen_at: datetime,
        announced_at: SourceEventClock | None = None,
        source_available_at: SourceEventClock | None = None,
        effective_at: SourceEventClock | None = None,
        supersedes_source_event_id: str | None = None,
        supersedes_source_revision_id: str | None = None,
    ) -> SecurityDisclosureEvent:
        """Bind typed source fields to the SHA-256 of the exact supplied document bytes."""

        if type(source_document_body) is not bytes or not source_document_body:
            raise ValueError("source_document_body must contain the exact non-empty source bytes")
        return cls(
            source=source,
            exchange=exchange,
            asset_code=asset_code,
            source_security_code=source_security_code,
            source_event_id=source_event_id,
            source_revision_id=source_revision_id,
            raw_event_type=raw_event_type,
            event_type=event_type,
            source_url=source_url,
            source_body_sha256=hashlib.sha256(source_document_body).hexdigest(),
            announced_at=announced_at,
            source_available_at=source_available_at,
            first_seen_at=first_seen_at,
            effective_at=effective_at,
            supersedes_source_event_id=supersedes_source_event_id,
            supersedes_source_revision_id=supersedes_source_revision_id,
        )

    def verifies_source_document(self, source_document_body: bytes) -> bool:
        """Verify that supplied original document bytes match this event's stored hash."""

        return (
            type(source_document_body) is bytes
            and bool(source_document_body)
            and hashlib.sha256(source_document_body).hexdigest() == self.source_body_sha256
        )

    @property
    def content_hash(self) -> str:
        """Hash the normalized event identity, clocks, category, URL, and source-body hash."""

        payload = {
            "source": self.source.value,
            "exchange": self.exchange.value,
            "asset_code": self.asset_code,
            "source_security_code": self.source_security_code,
            "source_event_id": self.source_event_id,
            "source_revision_id": self.source_revision_id,
            "raw_event_type": self.raw_event_type,
            "event_type": self.event_type.value,
            "source_url": self.source_url,
            "source_body_sha256": self.source_body_sha256,
            "announced_at": _clock_payload(self.announced_at),
            "source_available_at": _clock_payload(self.source_available_at),
            "effective_at": _clock_payload(self.effective_at),
            "supersedes_source_event_id": self.supersedes_source_event_id,
            "supersedes_source_revision_id": self.supersedes_source_revision_id,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SecurityDisclosureEventReadScope:
    """A public-knowledge cutoff and optional exact security scope."""

    as_of: datetime
    exchange: SecurityDisclosureExchange | None = None
    asset_code: str | None = None

    def __post_init__(self) -> None:
        """Reject naive clocks and mismatched exchange filters."""

        if type(self.as_of) is not datetime or self.as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        if self.as_of.utcoffset() is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        if self.exchange is not None and type(self.exchange) is not SecurityDisclosureExchange:
            raise ValueError("exchange filter must be an exact supported exchange")
        if self.asset_code is not None:
            _required_text(self.asset_code, field_name="asset_code", maximum=20)
            if not _CANONICAL_SECURITY_CODE.fullmatch(self.asset_code):
                raise ValueError("asset_code filter must be a canonical SSE or SZSE code")
            suffix = ".SH" if self.asset_code.endswith(".SH") else ".SZ"
            if self.exchange is not None:
                expected_suffix = (
                    ".SH" if self.exchange is SecurityDisclosureExchange.SSE else ".SZ"
                )
                if suffix != expected_suffix:
                    raise ValueError("asset_code and exchange filters disagree")


@dataclass(frozen=True, slots=True)
class PersistedSecurityDisclosureEvent:
    """One source disclosure plus the Data Center's first record time."""

    event: SecurityDisclosureEvent
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Verify the persistence clock remains later than public availability."""

        if type(self.event) is not SecurityDisclosureEvent:
            raise ValueError("event must be a SecurityDisclosureEvent")
        if type(self.recorded_at) is not datetime:
            raise ValueError("recorded_at must be a timezone-aware datetime")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be a timezone-aware datetime")
        if self.event.available_at > self.recorded_at:
            raise ValueError("recorded_at cannot precede source availability")


class SecurityDisclosureEventAppendDisposition(StrEnum):
    """Whether an append inserted a first winner or returned an exact duplicate."""

    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class SecurityDisclosureEventAppendResult:
    """Idempotent append outcome with the persisted source event record."""

    disposition: SecurityDisclosureEventAppendDisposition
    record: PersistedSecurityDisclosureEvent

    def __post_init__(self) -> None:
        """Require the normalized append result and exact persisted record."""

        if type(self.disposition) is not SecurityDisclosureEventAppendDisposition:
            raise ValueError("disposition must be an exact append outcome")
        if type(self.record) is not PersistedSecurityDisclosureEvent:
            raise ValueError("record must be a persisted security disclosure event")


__all__ = [
    "PersistedSecurityDisclosureEvent",
    "SecurityDisclosureEvent",
    "SecurityDisclosureEventAppendDisposition",
    "SecurityDisclosureEventAppendResult",
    "SecurityDisclosureEventReadScope",
    "SecurityDisclosureEventType",
    "SecurityDisclosureExchange",
    "SecurityDisclosureSource",
    "SourceEventClock",
]
