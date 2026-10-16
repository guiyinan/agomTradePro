"""Closed-vocabulary contracts for exchange-calendar publication audit events.

Calendar publication is a global reference-data operation rather than a
tenant/owner operation.  This module allows exactly two v1 event shapes to use
``scope=None``; it does not change the generic System Audit scope contract or
authorize a publisher or reader.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from uuid import UUID

from .system_audit_event import (
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)

CALENDAR_PUBLICATION_PUBLISHED_EVENT: Final[str] = "data.calendar.publication.published"
CALENDAR_PUBLICATION_BLOCKED_EVENT: Final[str] = "data.calendar.publication.blocked"
CALENDAR_PUBLICATION_PUBLISHED_DETAIL_SCHEMA: Final[str] = "data.calendar.publication.published.v1"
CALENDAR_PUBLICATION_BLOCKED_DETAIL_SCHEMA: Final[str] = "data.calendar.publication.blocked.v1"
CALENDAR_PUBLICATION_OWNER: Final[str] = "data_center"
CALENDAR_PUBLICATION_COMPONENT: Final[str] = "calendar_publication"
CALENDAR_PUBLICATION_STREAM_PREFIX: Final[str] = "data.calendar.publication:"
CALENDAR_PUBLISH_PERMISSION: Final[str] = "publish_exchange_calendar"
CALENDAR_SESSION_AUTHENTICATION: Final[str] = "session"
CALENDAR_PUBLISHED_REASON: Final[str] = "calendar_publication_published"
CALENDAR_BLOCKED_REASON: Final[str] = "calendar_publication_blocked"
_EVENT_VERSION: Final[str] = "1"
_ENVELOPE_VERSION: Final[str] = "system-audit-event.v1"
_PLAIN_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_PREFIXED_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_REASON_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class CalendarPublicationAuditContractError(ValueError):
    """Recognized invalid calendar Audit contract with a stable error code."""

    def __init__(self, code: str, message: str) -> None:
        """Store the stable code without depending on an application layer."""

        self.code = code
        super().__init__(message)


def calendar_publication_stream_id(dataset_key: str, exchange: str) -> str:
    """Return the deterministic stream for one exact dataset and exchange pair."""

    _require_token(dataset_key, "dataset_key")
    _require_token(exchange, "exchange")
    material = f"audit-calendar-stream-v1\0{dataset_key}\0{exchange}".encode()
    return f"{CALENDAR_PUBLICATION_STREAM_PREFIX}{hashlib.sha256(material).hexdigest()}"


def calendar_publication_event_identity(
    *,
    event_kind: str,
    dataset_key: str,
    exchange: str,
    request_identity: str,
) -> tuple[str, str]:
    """Return stable event and idempotency identities for one request outcome."""

    if type(event_kind) is not str or event_kind not in {"published", "blocked"}:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_KIND_INVALID", "calendar audit event kind is unsupported"
        )
    _require_token(dataset_key, "dataset_key")
    _require_token(exchange, "exchange")
    _require_token(request_identity, "request_identity")
    material = "\0".join(
        ("audit-calendar-event-v1", event_kind, dataset_key, exchange, request_identity)
    ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    identity = f"calendar:{event_kind}:{digest}"
    return identity, identity


@dataclass(frozen=True, slots=True)
class CalendarPublicationAuditEvidence:
    """Exact fact-row, snapshot, and original-provider-response binding.

    ``fact_content_hash`` is the unprefixed 64-character publication-member
    hash of the stored fact row.  Snapshot and RawPayload content/record hashes
    preserve their distinct ``sha256:`` forms. ``first_seen_at`` and
    ``response_completed_at`` are local response-completion clocks; they are
    never promoted to upstream observation or publication time.
    """

    snapshot_id: str
    exchange: str
    coverage_start: date
    coverage_end: date
    provider_name: str
    first_seen_at: datetime
    snapshot_recorded_at: datetime
    source_published_at: datetime | None
    fact_content_hash: str
    snapshot_content_hash: str
    snapshot_record_digest: str
    raw_payload_id: str
    raw_payload_hash: str
    raw_record_digest: str
    raw_body_sha256: str
    raw_retained_content_sha256: str
    raw_request_scope_sha256: str
    original_body_retained: bool
    response_completed_at: datetime
    raw_provider_name: str
    raw_dataset_key: str
    raw_transport: str

    def __post_init__(self) -> None:
        """Validate each source identity, timestamp, and hash by its own meaning."""

        _require_uuid(self.snapshot_id, "snapshot_id")
        _require_token(self.exchange, "exchange")
        _require_date(self.coverage_start, "coverage_start")
        _require_date(self.coverage_end, "coverage_end")
        if self.coverage_start > self.coverage_end:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EVIDENCE_INVALID", "snapshot coverage is reversed"
            )
        _require_token(self.provider_name, "provider_name")
        _require_time(self.first_seen_at, "first_seen_at")
        _require_time(self.snapshot_recorded_at, "snapshot_recorded_at")
        if self.source_published_at is not None:
            _require_time(self.source_published_at, "source_published_at")
        if self.snapshot_recorded_at < self.first_seen_at:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_KNOWLEDGE_TIME_INVALID",
                "snapshot recorded_at precedes local first_seen_at",
            )
        _require_plain_digest(self.fact_content_hash, "fact_content_hash")
        _require_prefixed_digest(self.snapshot_content_hash, "snapshot_content_hash")
        _require_prefixed_digest(self.snapshot_record_digest, "snapshot_record_digest")
        _require_uuid(self.raw_payload_id, "raw_payload_id")
        _require_prefixed_digest(self.raw_payload_hash, "raw_payload_hash")
        _require_prefixed_digest(self.raw_record_digest, "raw_record_digest")
        _require_plain_digest(self.raw_body_sha256, "raw_body_sha256")
        _require_plain_digest(self.raw_retained_content_sha256, "raw_retained_content_sha256")
        _require_plain_digest(self.raw_request_scope_sha256, "raw_request_scope_sha256")
        if type(self.original_body_retained) is not bool:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EVIDENCE_INVALID", "original_body_retained must be bool"
            )
        _require_time(self.response_completed_at, "response_completed_at")
        if self.first_seen_at != self.response_completed_at:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_FIRST_SEEN_MISMATCH",
                "first_seen_at must equal the RawPayload response completion time",
            )
        _require_token(self.raw_provider_name, "raw_provider_name")
        _require_token(self.raw_dataset_key, "raw_dataset_key")
        _require_token(self.raw_transport, "raw_transport")
        if self.provider_name != self.raw_provider_name:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_PROVIDER_MISMATCH",
                "snapshot and RawPayload providers differ",
            )

    def to_payload(self) -> dict[str, JSONValue]:
        """Return an exact nested source binding without merging hash meanings."""

        return {
            "snapshot": {
                "snapshot_id": self.snapshot_id,
                "exchange": self.exchange,
                "coverage_start": self.coverage_start.isoformat(),
                "coverage_end": self.coverage_end.isoformat(),
                "provider_name": self.provider_name,
                "first_seen_at": _utc_text(self.first_seen_at),
                "recorded_at": _utc_text(self.snapshot_recorded_at),
                "source_published_at": (
                    _utc_text(self.source_published_at)
                    if self.source_published_at is not None
                    else None
                ),
                "fact_content_hash": self.fact_content_hash,
                "content_hash": self.snapshot_content_hash,
                "record_digest": self.snapshot_record_digest,
            },
            "raw_reference": {
                "payload_id": self.raw_payload_id,
                "payload_hash": self.raw_payload_hash,
                "record_digest": self.raw_record_digest,
                "body_sha256": self.raw_body_sha256,
                "retained_content_sha256": self.raw_retained_content_sha256,
                "request_scope_sha256": self.raw_request_scope_sha256,
                "original_body_retained": self.original_body_retained,
                "response_completed_at": _utc_text(self.response_completed_at),
                "response_time_semantics": "local_response_body_completion",
                "provider_name": self.raw_provider_name,
                "dataset_key": self.raw_dataset_key,
                "transport": self.raw_transport,
            },
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarPublicationAuditEvidence:
        """Restore and strictly validate one exact nested source binding."""

        root = _mapping(payload, "snapshot_evidence", {"snapshot", "raw_reference"})
        snapshot = _mapping(
            root["snapshot"],
            "snapshot_evidence.snapshot",
            {
                "snapshot_id",
                "exchange",
                "coverage_start",
                "coverage_end",
                "provider_name",
                "first_seen_at",
                "recorded_at",
                "source_published_at",
                "fact_content_hash",
                "content_hash",
                "record_digest",
            },
        )
        raw = _mapping(
            root["raw_reference"],
            "snapshot_evidence.raw_reference",
            {
                "payload_id",
                "payload_hash",
                "record_digest",
                "body_sha256",
                "retained_content_sha256",
                "request_scope_sha256",
                "original_body_retained",
                "response_completed_at",
                "response_time_semantics",
                "provider_name",
                "dataset_key",
                "transport",
            },
        )
        if raw["response_time_semantics"] != "local_response_body_completion":
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_RAW_CLOCK_SEMANTICS_INVALID",
                "RawPayload completion time semantics are not canonical",
            )
        return cls(
            snapshot_id=_text(snapshot["snapshot_id"], "snapshot.snapshot_id"),
            exchange=_text(snapshot["exchange"], "snapshot.exchange"),
            coverage_start=_date(snapshot["coverage_start"], "snapshot.coverage_start"),
            coverage_end=_date(snapshot["coverage_end"], "snapshot.coverage_end"),
            provider_name=_text(snapshot["provider_name"], "snapshot.provider_name"),
            first_seen_at=_parse_utc(snapshot["first_seen_at"], "snapshot.first_seen_at"),
            snapshot_recorded_at=_parse_utc(snapshot["recorded_at"], "snapshot.recorded_at"),
            source_published_at=(
                None
                if snapshot["source_published_at"] is None
                else _parse_utc(snapshot["source_published_at"], "snapshot.source_published_at")
            ),
            fact_content_hash=_text(snapshot["fact_content_hash"], "snapshot.fact_content_hash"),
            snapshot_content_hash=_text(snapshot["content_hash"], "snapshot.content_hash"),
            snapshot_record_digest=_text(snapshot["record_digest"], "snapshot.record_digest"),
            raw_payload_id=_text(raw["payload_id"], "raw_reference.payload_id"),
            raw_payload_hash=_text(raw["payload_hash"], "raw_reference.payload_hash"),
            raw_record_digest=_text(raw["record_digest"], "raw_reference.record_digest"),
            raw_body_sha256=_text(raw["body_sha256"], "raw_reference.body_sha256"),
            raw_retained_content_sha256=_text(
                raw["retained_content_sha256"], "raw_reference.retained_content_sha256"
            ),
            raw_request_scope_sha256=_text(
                raw["request_scope_sha256"], "raw_reference.request_scope_sha256"
            ),
            original_body_retained=_bool(
                raw["original_body_retained"], "raw_reference.original_body_retained"
            ),
            response_completed_at=_parse_utc(
                raw["response_completed_at"], "raw_reference.response_completed_at"
            ),
            raw_provider_name=_text(raw["provider_name"], "raw_reference.provider_name"),
            raw_dataset_key=_text(raw["dataset_key"], "raw_reference.dataset_key"),
            raw_transport=_text(raw["transport"], "raw_reference.transport"),
        )


@dataclass(frozen=True, slots=True)
class CalendarPublicationPublishedDetail:
    """Exact detail schema for a successfully published calendar snapshot."""

    dataset_key: str
    exchange: str
    publication_id: str
    publication_key: str
    policy_version: str
    publication_hash: str
    snapshot_evidence: CalendarPublicationAuditEvidence

    def __post_init__(self) -> None:
        """Require one exact publication and its matching source snapshot."""

        for name in (
            "dataset_key",
            "exchange",
            "publication_id",
            "publication_key",
            "policy_version",
        ):
            _require_token(getattr(self, name), name)
        _require_plain_digest(self.publication_hash, "publication_hash")
        if type(self.snapshot_evidence) is not CalendarPublicationAuditEvidence:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EVIDENCE_INVALID", "snapshot_evidence must use its typed contract"
            )
        CalendarPublicationAuditEvidence.__post_init__(self.snapshot_evidence)
        if self.snapshot_evidence.exchange != self.exchange:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EXCHANGE_MISMATCH", "publication and snapshot exchanges differ"
            )
        if self.snapshot_evidence.raw_dataset_key != self.dataset_key:
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_DATASET_MISMATCH",
                "publication dataset and RawPayload dataset differ",
            )

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the exact v1 published detail object."""

        return {
            "authentication_mode": CALENDAR_SESSION_AUTHENTICATION,
            "permission_codename": CALENDAR_PUBLISH_PERMISSION,
            "dataset_key": self.dataset_key,
            "exchange": self.exchange,
            "publication_id": self.publication_id,
            "publication_key": self.publication_key,
            "policy_version": self.policy_version,
            "publication_hash": self.publication_hash,
            "snapshot_evidence": self.snapshot_evidence.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarPublicationPublishedDetail:
        """Restore only the exact published schema and fixed authorization labels."""

        value = _mapping(
            payload,
            "calendar_publication_published.detail",
            {
                "authentication_mode",
                "permission_codename",
                "dataset_key",
                "exchange",
                "publication_id",
                "publication_key",
                "policy_version",
                "publication_hash",
                "snapshot_evidence",
            },
        )
        _require_fixed(value, "authentication_mode", CALENDAR_SESSION_AUTHENTICATION)
        _require_fixed(value, "permission_codename", CALENDAR_PUBLISH_PERMISSION)
        return cls(
            dataset_key=_text(value["dataset_key"], "detail.dataset_key"),
            exchange=_text(value["exchange"], "detail.exchange"),
            publication_id=_text(value["publication_id"], "detail.publication_id"),
            publication_key=_text(value["publication_key"], "detail.publication_key"),
            policy_version=_text(value["policy_version"], "detail.policy_version"),
            publication_hash=_text(value["publication_hash"], "detail.publication_hash"),
            snapshot_evidence=CalendarPublicationAuditEvidence.from_payload(
                value["snapshot_evidence"]
            ),
        )


@dataclass(frozen=True, slots=True)
class CalendarPublicationBlockedDetail:
    """Exact detail schema for a blocked calendar-publication attempt."""

    dataset_key: str
    exchange: str
    request_id: str
    blocked_reason: str
    snapshot_evidence: CalendarPublicationAuditEvidence | None = None
    publication_id: str | None = None

    def __post_init__(self) -> None:
        """Validate the request, stable block reason, and optional exact evidence."""

        for name in ("dataset_key", "exchange", "request_id"):
            _require_token(getattr(self, name), name)
        if self.publication_id is not None:
            _require_token(self.publication_id, "publication_id")
        if (
            type(self.blocked_reason) is not str
            or len(self.blocked_reason) > 128
            or _REASON_RE.fullmatch(self.blocked_reason) is None
        ):
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_BLOCK_REASON_INVALID", "blocked_reason is not canonical"
            )
        if self.snapshot_evidence is not None:
            if type(self.snapshot_evidence) is not CalendarPublicationAuditEvidence:
                raise CalendarPublicationAuditContractError(
                    "CALENDAR_AUDIT_EVIDENCE_INVALID",
                    "snapshot_evidence must use its typed contract",
                )
            CalendarPublicationAuditEvidence.__post_init__(self.snapshot_evidence)
            if self.snapshot_evidence.exchange != self.exchange:
                raise CalendarPublicationAuditContractError(
                    "CALENDAR_AUDIT_EXCHANGE_MISMATCH",
                    "blocked request and candidate snapshot exchanges differ",
                )
            if self.snapshot_evidence.raw_dataset_key != self.dataset_key:
                raise CalendarPublicationAuditContractError(
                    "CALENDAR_AUDIT_DATASET_MISMATCH",
                    "blocked request and RawPayload datasets differ",
                )

    def to_payload(self) -> dict[str, JSONValue]:
        """Return the exact v1 blocked detail object."""

        return {
            "authentication_mode": CALENDAR_SESSION_AUTHENTICATION,
            "permission_codename": CALENDAR_PUBLISH_PERMISSION,
            "dataset_key": self.dataset_key,
            "exchange": self.exchange,
            "request_id": self.request_id,
            "publication_id": self.publication_id,
            "blocked_reason": self.blocked_reason,
            "snapshot_evidence": (
                self.snapshot_evidence.to_payload() if self.snapshot_evidence is not None else None
            ),
        }

    @classmethod
    def from_payload(cls, payload: object) -> CalendarPublicationBlockedDetail:
        """Restore only the exact blocked schema and fixed authorization labels."""

        value = _mapping(
            payload,
            "calendar_publication_blocked.detail",
            {
                "authentication_mode",
                "permission_codename",
                "dataset_key",
                "exchange",
                "request_id",
                "publication_id",
                "blocked_reason",
                "snapshot_evidence",
            },
        )
        _require_fixed(value, "authentication_mode", CALENDAR_SESSION_AUTHENTICATION)
        _require_fixed(value, "permission_codename", CALENDAR_PUBLISH_PERMISSION)
        evidence = value["snapshot_evidence"]
        return cls(
            dataset_key=_text(value["dataset_key"], "detail.dataset_key"),
            exchange=_text(value["exchange"], "detail.exchange"),
            request_id=_text(value["request_id"], "detail.request_id"),
            blocked_reason=_text(value["blocked_reason"], "detail.blocked_reason"),
            snapshot_evidence=(
                None
                if evidence is None
                else CalendarPublicationAuditEvidence.from_payload(evidence)
            ),
            publication_id=(
                None
                if value["publication_id"] is None
                else _text(value["publication_id"], "detail.publication_id")
            ),
        )


def validate_calendar_publication_event(event: SystemAuditEvent) -> None:
    """Validate a complete event against one of the two calendar v1 contracts."""

    if type(event) is not SystemAuditEvent:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_INVALID", "event must be an exact SystemAuditEvent"
        )
    try:
        event.validate_hashes()
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_HASH_INVALID", "event hashes are invalid"
        ) from error
    if event.event_type == CALENDAR_PUBLICATION_PUBLISHED_EVENT:
        published_detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
        expected_correlations = AuditCorrelations(
            dataset_key=published_detail.dataset_key,
            capability="calendar.publication",
            publication_id=published_detail.publication_id,
            evidence_ref=_snapshot_evidence_correlation(published_detail.snapshot_evidence),
        )
        _validate_common_event(
            event,
            published_detail.dataset_key,
            published_detail.exchange,
            expected_correlations,
        )
        request_identity = published_detail.publication_id
        event_id, idempotency_key = calendar_publication_event_identity(
            event_kind="published",
            dataset_key=published_detail.dataset_key,
            exchange=published_detail.exchange,
            request_identity=request_identity,
        )
        evidence = published_detail.snapshot_evidence
        expected_published_refs = (_snapshot_evidence_ref(evidence),)
        expected_resource = AuditResourceRef(
            "canonical_publication",
            published_detail.publication_id,
            published_detail.publication_hash,
        )
        if (
            event.detail_schema != CALENDAR_PUBLICATION_PUBLISHED_DETAIL_SCHEMA
            or event.outcome is not AuditOutcome.PUBLISHED
            or event.severity is not AuditSeverity.INFO
            or event.reason_codes != (CALENDAR_PUBLISHED_REASON,)
            or event.publication_id != published_detail.publication_id
            or event.resource != expected_resource
            or event.evidence_refs != expected_published_refs
            or event.recorded_at < evidence.snapshot_recorded_at
        ):
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EVENT_FIELDS_INVALID", "published event fields do not match detail"
            )
    elif event.event_type == CALENDAR_PUBLICATION_BLOCKED_EVENT:
        blocked_detail = CalendarPublicationBlockedDetail.from_payload(event.detail)
        expected_correlations = AuditCorrelations(
            request_id=blocked_detail.request_id,
            dataset_key=blocked_detail.dataset_key,
            capability="calendar.publication",
            publication_id=blocked_detail.publication_id,
            evidence_ref=(
                _snapshot_evidence_correlation(blocked_detail.snapshot_evidence)
                if blocked_detail.snapshot_evidence is not None
                else f"calendar-publication-attempt:{blocked_detail.request_id}"
            ),
        )
        _validate_common_event(
            event,
            blocked_detail.dataset_key,
            blocked_detail.exchange,
            expected_correlations,
        )
        event_id, idempotency_key = calendar_publication_event_identity(
            event_kind="blocked",
            dataset_key=blocked_detail.dataset_key,
            exchange=blocked_detail.exchange,
            request_identity=blocked_detail.request_id,
        )
        expected_blocked_refs = (
            (_snapshot_evidence_ref(blocked_detail.snapshot_evidence),)
            if blocked_detail.snapshot_evidence is not None
            else ()
        )
        expected_resource = (
            AuditResourceRef("canonical_publication", blocked_detail.publication_id)
            if blocked_detail.publication_id is not None
            else AuditResourceRef("calendar_publication_attempt", blocked_detail.request_id)
        )
        if (
            event.detail_schema != CALENDAR_PUBLICATION_BLOCKED_DETAIL_SCHEMA
            or event.outcome is not AuditOutcome.BLOCKED
            or event.severity is not AuditSeverity.WARNING
            or event.reason_codes != (CALENDAR_BLOCKED_REASON,)
            or event.publication_id != blocked_detail.publication_id
            or event.resource != expected_resource
            or event.evidence_refs != expected_blocked_refs
            or (
                blocked_detail.snapshot_evidence is not None
                and event.recorded_at < blocked_detail.snapshot_evidence.snapshot_recorded_at
            )
        ):
            raise CalendarPublicationAuditContractError(
                "CALENDAR_AUDIT_EVENT_FIELDS_INVALID", "blocked event fields do not match detail"
            )
    else:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_TYPE_UNSUPPORTED", "unregistered calendar audit event type"
        )
    if event.event_id != event_id or event.idempotency_key != idempotency_key:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_IDENTITY_INVALID", "event identity is not deterministic"
        )


def calendar_publication_event_selector(event: SystemAuditEvent) -> tuple[str, str]:
    """Return a validated event's exact dataset and exchange selector."""

    validate_calendar_publication_event(event)
    if event.event_type == CALENDAR_PUBLICATION_PUBLISHED_EVENT:
        published_detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
        return published_detail.dataset_key, published_detail.exchange
    blocked_detail = CalendarPublicationBlockedDetail.from_payload(event.detail)
    return blocked_detail.dataset_key, blocked_detail.exchange


def _validate_common_event(
    event: SystemAuditEvent,
    dataset_key: str,
    exchange: str,
    expected_correlations: AuditCorrelations,
) -> None:
    """Check closed envelope fields shared by both event variants."""

    _require_time(event.recorded_at, "recorded_at")
    _require_time(event.occurred_at, "occurred_at")
    if (
        event.event_version != _EVENT_VERSION
        or event.schema_version != _ENVELOPE_VERSION
        or event.category is not AuditCategory.DATA_RELIABILITY
        or event.owner != CALENDAR_PUBLICATION_OWNER
        or event.write_policy is not AuditWritePolicy.TRANSACTIONAL_OUTBOX
        or event.observed_at is not None
        or event.actor.actor_type != "django_user"
        or re.fullmatch(r"django-user:[1-9][0-9]*", event.actor.actor_id) is None
        or event.actor.actor_display is not None
        or event.source_app != "data_center"
        or event.source_component != CALENDAR_PUBLICATION_COMPONENT
        or event.source_surface != "internal"
        or event.scope is not None
        or event.stream_id != calendar_publication_stream_id(dataset_key, exchange)
        or event.dataset_key != dataset_key
        or event.provider_key is not None
        or event.capability != "calendar.publication"
        or event.correlations != expected_correlations
        or event.occurred_at != event.recorded_at
    ):
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_EVENT_FIELDS_INVALID",
            "event does not match the common calendar contract",
        )


def _snapshot_evidence_ref(evidence: CalendarPublicationAuditEvidence) -> AuditEvidenceRef:
    """Build the single canonical AuditEvidenceRef for a calendar fact row."""

    return AuditEvidenceRef(
        owner=CALENDAR_PUBLICATION_OWNER,
        artifact_type="exchange_calendar_snapshot_fact",
        artifact_id=evidence.snapshot_id,
        artifact_version=evidence.snapshot_record_digest,
        content_hash=evidence.fact_content_hash,
    )


def _snapshot_evidence_correlation(evidence: CalendarPublicationAuditEvidence) -> str:
    """Return the exact snapshot/fact-hash correlation token."""

    return f"calendar-snapshot:{evidence.snapshot_id}:{evidence.fact_content_hash}"


def _require_token(value: object, field_name: str) -> None:
    """Require a bounded whitespace-free string token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 192
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TOKEN_INVALID", f"{field_name} must be a bounded canonical token"
        )


def _require_plain_digest(value: object, field_name: str) -> None:
    """Require an unprefixed lowercase SHA-256 content hash."""

    if type(value) is not str or _PLAIN_SHA256_RE.fullmatch(value) is None:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_HASH_INVALID", f"{field_name} must be a lowercase SHA-256 digest"
        )


def _require_prefixed_digest(value: object, field_name: str) -> None:
    """Require a ``sha256:``-prefixed persisted content or record digest."""

    if type(value) is not str or _PREFIXED_SHA256_RE.fullmatch(value) is None:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_HASH_INVALID", f"{field_name} must be a prefixed SHA-256 digest"
        )


def _require_uuid(value: str, field_name: str) -> None:
    """Require the canonical string representation of a UUID identity."""

    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError) as error:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_UUID_INVALID", f"{field_name} must be a canonical UUID"
        ) from error


def _require_date(value: date, field_name: str) -> None:
    """Require a date without accepting a datetime subclass."""

    if type(value) is not date:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DATE_INVALID", f"{field_name} must be a date"
        )


def _date(value: object, field_name: str) -> date:
    """Parse and revalidate one canonical ISO calendar date."""

    text = _text(value, field_name)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DATE_INVALID", f"{field_name} is not an ISO date"
        ) from error
    if parsed.isoformat() != text:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DATE_INVALID", f"{field_name} is not canonical"
        )
    return parsed


def _require_time(value: datetime, field_name: str) -> None:
    """Require an aware UTC datetime with no naive-clock interpretation."""

    if type(value) is not datetime:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TIME_INVALID", f"{field_name} must be UTC-aware"
        )
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TIME_INVALID", f"{field_name} must be UTC-aware"
        )


def _utc_text(value: datetime) -> str:
    """Serialize an aware instant as canonical UTC-Z microseconds."""

    _require_time(value, "datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object, field_name: str) -> datetime:
    """Parse only the envelope's canonical UTC-Z timestamp form."""

    text = _text(value, field_name)
    if len(text) != 27 or not text.endswith("Z") or "." not in text:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TIME_INVALID", f"{field_name} must use UTC-Z microseconds"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TIME_INVALID", f"{field_name} is invalid"
        ) from error
    if _utc_text(parsed) != text:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_TIME_INVALID", f"{field_name} is not canonical"
        )
    return parsed


def _mapping(value: object, field_name: str, keys: set[str]) -> Mapping[str, JSONValue]:
    """Require exact object keys before reading values from a JSON mapping."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DETAIL_INVALID", f"{field_name} must be an object"
        )
    if set(value) != keys:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DETAIL_INVALID", f"{field_name} has unknown or missing keys"
        )
    return value


def _text(value: object, field_name: str) -> str:
    """Require exact JSON string type."""

    if type(value) is not str:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DETAIL_INVALID", f"{field_name} must be a string"
        )
    return value


def _bool(value: object, field_name: str) -> bool:
    """Require exact JSON boolean type, excluding integer lookalikes."""

    if type(value) is not bool:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_DETAIL_INVALID", f"{field_name} must be a boolean"
        )
    return value


def _require_fixed(value: Mapping[str, JSONValue], key: str, expected: str) -> None:
    """Reject attribution or permission labels that differ from the v1 contract."""

    if value[key] != expected:
        raise CalendarPublicationAuditContractError(
            "CALENDAR_AUDIT_AUTHORIZATION_LABEL_INVALID", f"{key} is not canonical"
        )


__all__ = [
    "CALENDAR_BLOCKED_REASON",
    "CALENDAR_PUBLISH_PERMISSION",
    "CALENDAR_PUBLICATION_BLOCKED_DETAIL_SCHEMA",
    "CALENDAR_PUBLICATION_BLOCKED_EVENT",
    "CALENDAR_PUBLICATION_PUBLISHED_DETAIL_SCHEMA",
    "CALENDAR_PUBLICATION_PUBLISHED_EVENT",
    "CALENDAR_PUBLICATION_STREAM_PREFIX",
    "CALENDAR_PUBLISHED_REASON",
    "CALENDAR_SESSION_AUTHENTICATION",
    "CalendarPublicationAuditContractError",
    "CalendarPublicationAuditEvidence",
    "CalendarPublicationBlockedDetail",
    "CalendarPublicationPublishedDetail",
    "calendar_publication_event_identity",
    "calendar_publication_event_selector",
    "calendar_publication_stream_id",
    "validate_calendar_publication_event",
]
