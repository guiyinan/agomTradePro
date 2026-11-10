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
from uuid import UUID

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
    CORRECTION_NOTICE = "correction_notice"
    RIGHTS_ISSUE = "rights_issue"
    SHARE_UNLOCK = "share_unlock"
    REDUCTION = "reduction"
    REPURCHASE = "repurchase"
    OTHER = "other"
    UNKNOWN = "unknown"


class SecurityDisclosureListingCoverageStatus(StrEnum):
    """Result of checking one exact official listing window at a knowledge cutoff."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    MISSING = "missing"


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
class SecurityDisclosureListingEntry:
    """One exact official SZSE list row with date-precision publication evidence."""

    listing_id: str
    announcement_id: int
    title: str
    published_on: date
    raw_publish_time: str
    source_document_id: str
    source_url: str

    def __post_init__(self) -> None:
        """Validate source-native identities and preserve the published date precision."""

        for field_name in ("listing_id", "source_document_id"):
            value = getattr(self, field_name)
            if type(value) is not str:
                raise ValueError(f"{field_name} must be a canonical UUID")
            try:
                parsed = UUID(value)
            except ValueError as error:
                raise ValueError(f"{field_name} must be a canonical UUID") from error
            if str(parsed) != value.lower():
                raise ValueError(f"{field_name} must be a canonical UUID")
        if type(self.announcement_id) is not int or self.announcement_id <= 0:
            raise ValueError("announcement_id must be positive")
        _required_text(self.title, field_name="title", maximum=320)
        if type(self.published_on) is not date or type(self.published_on) is datetime:
            raise ValueError("published_on must preserve date precision")
        if (
            type(self.raw_publish_time) is not str
            or re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", self.raw_publish_time) is None
            or date.fromisoformat(self.raw_publish_time[:10]) != self.published_on
        ):
            raise ValueError("raw_publish_time must retain its source date and precision")
        _required_text(self.source_url, field_name="source_url", maximum=2048)
        _validate_source_url(self.source_url, source=SecurityDisclosureSource.SZSE_OFFICIAL)
        parsed_url = urlsplit(self.source_url)
        if not parsed_url.path.lower().endswith(f"/{self.source_document_id}.pdf"):
            raise ValueError("source_document_id does not match the official PDF URL")

    def to_manifest_payload(self) -> dict[str, object]:
        """Return the exact canonical listing row stored in its coverage manifest."""

        return {
            "listing_id": self.listing_id,
            "announcement_id": self.announcement_id,
            "title": self.title,
            "published_on": self.published_on.isoformat(),
            "raw_publish_time": self.raw_publish_time,
            "source_document_id": self.source_document_id,
            "source_url": self.source_url,
        }


def _require_listing_digest(value: object, *, field_name: str) -> None:
    """Require one lowercase SHA-256 used by the official listing proof."""

    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class SecurityDisclosureListingCoverageProof:
    """Exact two-pass SZSE listing proof and the time its downstream ingestion completed."""

    source: SecurityDisclosureSource
    exchange: SecurityDisclosureExchange
    asset_code: str
    start_on: date
    end_on: date
    first_observed_at: datetime
    verified_at: datetime
    announcement_count: int
    entries: tuple[SecurityDisclosureListingEntry, ...]
    first_pass_page_body_sha256: tuple[str, ...]
    second_pass_page_body_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject a mismatched, unstable, or incomplete listing proof."""

        if self.source is not SecurityDisclosureSource.SZSE_OFFICIAL:
            raise ValueError("listing coverage requires the official SZSE source")
        if self.exchange is not SecurityDisclosureExchange.SZSE:
            raise ValueError("listing coverage requires the SZSE exchange")
        if (
            type(self.asset_code) is not str
            or re.fullmatch(r"[0-9]{6}\.SZ", self.asset_code) is None
        ):
            raise ValueError("asset_code must be a canonical SZSE security code")
        for field_name in ("start_on", "end_on"):
            value = getattr(self, field_name)
            if type(value) is not date or type(value) is datetime:
                raise ValueError(f"{field_name} must be a date")
        if self.start_on > self.end_on:
            raise ValueError("listing coverage date window is reversed")
        for field_name in ("first_observed_at", "verified_at"):
            value = getattr(self, field_name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.first_observed_at > self.verified_at:
            raise ValueError("listing verification cannot precede its first observation")
        if type(self.announcement_count) is not int or self.announcement_count < 0:
            raise ValueError("announcement_count must be non-negative")
        if type(self.entries) is not tuple or len(self.entries) != self.announcement_count:
            raise ValueError("listing entries must match the exact source count")
        if any(type(item) is not SecurityDisclosureListingEntry for item in self.entries):
            raise ValueError("listing entries must use the typed source row")
        listing_ids = tuple(item.listing_id for item in self.entries)
        announcement_ids = tuple(item.announcement_id for item in self.entries)
        document_ids = tuple(item.source_document_id for item in self.entries)
        if (
            len(listing_ids) != len(set(listing_ids))
            or len(announcement_ids) != len(set(announcement_ids))
            or len(document_ids) != len(set(document_ids))
        ):
            raise ValueError("listing rows must have unique listing, announcement, and PDF IDs")
        if any(not self.start_on <= item.published_on <= self.end_on for item in self.entries):
            raise ValueError("listing entry falls outside the exact requested date window")
        for field_name in ("first_pass_page_body_sha256", "second_pass_page_body_sha256"):
            hashes = getattr(self, field_name)
            if type(hashes) is not tuple or not hashes:
                raise ValueError(f"{field_name} must preserve every response page hash")
            for digest in hashes:
                _require_listing_digest(digest, field_name=field_name)
        if len(self.first_pass_page_body_sha256) != len(self.second_pass_page_body_sha256):
            raise ValueError("both complete listing passes must contain the same page count")

    @property
    def source_manifest_sha256(self) -> str:
        """Rebuild the original v1 SZSE manifest identity for historical compatibility."""

        payload = {
            "schema": "szse.announcement-window.v1",
            "asset_code": self.asset_code,
            "start_on": self.start_on.isoformat(),
            "end_on": self.end_on.isoformat(),
            "announcement_count": self.announcement_count,
            "entries": [item.to_manifest_payload() for item in self.entries],
            "page_body_sha256": self.second_pass_page_body_sha256,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def coverage_manifest_sha256(self) -> str:
        """Hash the v2 proof schema, including both complete page-hash passes."""

        payload = {
            "schema": "szse.announcement-window-coverage.v2",
            "source": self.source.value,
            "exchange": self.exchange.value,
            "asset_code": self.asset_code,
            "start_on": self.start_on.isoformat(),
            "end_on": self.end_on.isoformat(),
            "announcement_count": self.announcement_count,
            "entries": [item.to_manifest_payload() for item in self.entries],
            "first_pass_page_body_sha256": self.first_pass_page_body_sha256,
            "second_pass_page_body_sha256": self.second_pass_page_body_sha256,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def source_document_ids(self) -> tuple[str, ...]:
        """Return the ordered PDF identities declared by the source listing."""

        return tuple(item.source_document_id for item in self.entries)


@dataclass(frozen=True, slots=True)
class SecurityDisclosureListingCoverageReadScope:
    """Read one exact captured SZSE date window at a historical knowledge cutoff."""

    asset_code: str
    start_on: date
    end_on: date
    as_of: datetime

    def __post_init__(self) -> None:
        """Require an exact security/window and an aware, bounded candidate cutoff."""

        if (
            type(self.asset_code) is not str
            or re.fullmatch(r"[0-9]{6}\.SZ", self.asset_code) is None
        ):
            raise ValueError("asset_code must be a canonical SZSE security code")
        for field_name in ("start_on", "end_on"):
            value = getattr(self, field_name)
            if type(value) is not date or type(value) is datetime:
                raise ValueError(f"{field_name} must be a date")
        if self.start_on > self.end_on:
            raise ValueError("coverage read date window is reversed")
        if type(self.as_of) is not datetime or self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")


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


@dataclass(frozen=True, slots=True)
class PersistedSecurityDisclosureListingCoverage:
    """One append-only listing proof and the Data Center's first persistence time."""

    proof: SecurityDisclosureListingCoverageProof
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Ensure storage did not predate the completed source verification."""

        if type(self.proof) is not SecurityDisclosureListingCoverageProof:
            raise ValueError("proof must be an exact security disclosure listing proof")
        if type(self.recorded_at) is not datetime:
            raise ValueError("recorded_at must be a timezone-aware datetime")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be a timezone-aware datetime")
        if self.proof.verified_at > self.recorded_at:
            raise ValueError("recorded_at cannot precede listing verification")


@dataclass(frozen=True, slots=True)
class SecurityDisclosureListingCoverageSnapshot:
    """Historical listing proof and event revisions at its exact durable cutoff."""

    scope: SecurityDisclosureListingCoverageReadScope
    proof: PersistedSecurityDisclosureListingCoverage | None
    events: tuple[PersistedSecurityDisclosureEvent, ...]
    coverage_status: SecurityDisclosureListingCoverageStatus
    reason_code: str

    def __post_init__(self) -> None:
        """Prevent a missing or incomplete proof from presenting itself as complete."""

        if type(self.scope) is not SecurityDisclosureListingCoverageReadScope:
            raise ValueError("scope must be an exact listing coverage read request")
        if (
            self.proof is not None
            and type(self.proof) is not PersistedSecurityDisclosureListingCoverage
        ):
            raise ValueError("proof must be a persisted official listing proof")
        if type(self.events) is not tuple or any(
            type(item) is not PersistedSecurityDisclosureEvent for item in self.events
        ):
            raise ValueError("events must contain persisted official disclosure facts")
        if type(self.coverage_status) is not SecurityDisclosureListingCoverageStatus:
            raise ValueError("coverage_status must be a recognized status")
        _required_text(self.reason_code, field_name="reason_code", maximum=120)
        if self.coverage_status is SecurityDisclosureListingCoverageStatus.COMPLETE:
            if self.proof is None:
                raise ValueError("complete listing coverage requires a persisted proof")
            if (
                self.proof.proof.asset_code != self.scope.asset_code
                or self.proof.proof.start_on != self.scope.start_on
                or self.proof.proof.end_on != self.scope.end_on
                or self.proof.proof.verified_at > self.scope.as_of
                or self.proof.recorded_at != self.scope.as_of
            ):
                raise ValueError(
                    "complete listing coverage must match its exact persisted knowledge cutoff"
                )
            expected_entries = {item.source_document_id: item for item in self.proof.proof.entries}
            represented = tuple(item.event.source_event_id for item in self.events)
            if len(represented) != len(set(represented)) or set(represented) != set(
                expected_entries
            ):
                raise ValueError(
                    "complete listing coverage must represent each listed PDF exactly once"
                )
            for persisted in self.events:
                event = persisted.event
                entry = expected_entries[event.source_event_id]
                if (
                    event.source is not self.proof.proof.source
                    or event.exchange is not self.proof.proof.exchange
                    or event.asset_code != self.scope.asset_code
                    or event.source_security_code != self.scope.asset_code[:6]
                    or event.source_url != entry.source_url
                    or type(event.announced_at) is not date
                    or event.announced_at != entry.published_on
                ):
                    raise ValueError(
                        "complete listing coverage requires exact listed event identity"
                    )
            if any(
                item.event.event_type is SecurityDisclosureEventType.UNKNOWN for item in self.events
            ):
                raise ValueError("unknown event classification cannot be complete coverage")

    @property
    def source_scope_sha256(self) -> str | None:
        """Return the exact listing manifest hash when proof exists at this cutoff."""

        if self.proof is None:
            return None
        return self.proof.proof.coverage_manifest_sha256


@dataclass(frozen=True, slots=True)
class SecurityDisclosureListingCoverageAppendResult:
    """Idempotent listing-proof append outcome with its persisted first winner."""

    disposition: SecurityDisclosureEventAppendDisposition
    record: PersistedSecurityDisclosureListingCoverage

    def __post_init__(self) -> None:
        """Require a typed persistence disposition and exact proof record."""

        if type(self.disposition) is not SecurityDisclosureEventAppendDisposition:
            raise ValueError("disposition must be an exact append outcome")
        if type(self.record) is not PersistedSecurityDisclosureListingCoverage:
            raise ValueError("record must be a persisted security disclosure listing proof")


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
    "PersistedSecurityDisclosureListingCoverage",
    "SecurityDisclosureListingCoverageAppendResult",
    "SecurityDisclosureListingCoverageProof",
    "SecurityDisclosureListingCoverageReadScope",
    "SecurityDisclosureListingCoverageSnapshot",
    "SecurityDisclosureListingCoverageStatus",
    "SecurityDisclosureListingEntry",
    "SecurityDisclosureEvent",
    "SecurityDisclosureEventAppendDisposition",
    "SecurityDisclosureEventAppendResult",
    "SecurityDisclosureEventReadScope",
    "SecurityDisclosureEventType",
    "SecurityDisclosureExchange",
    "SecurityDisclosureSource",
    "SourceEventClock",
]
