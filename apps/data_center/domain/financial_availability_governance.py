"""Typed C2 rule and policy configuration plus local Owner lifecycle evidence.

These values describe database records and their hashes. They do not prove
that a Django permission was checked, that a source body is official, or that
a formal calendar publication / E1 audit lease is valid. Those claims require
independent infrastructure reads in the owning transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import TypeAlias
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
    ExchangeSessionOpeningRule,
    exchange_session_opening_rule_sha256,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    exchange_calendar_publication_key,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDocumentRevision,
)

FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME = "manage_financial_availability_governance"
FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL = "data_center"
_RULE_VERSION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_RULE_PROPOSAL_HASH_DOMAIN = b"data_center.exchange-session-opening-rule-proposal.v1\0"
_GOVERNANCE_RECORD_HASH_DOMAIN = b"data_center.financial-availability-record.v1\0"
_OWNER_EVENT_HASH_DOMAIN = b"data_center.financial-availability-owner-event.v1\0"


class FinancialAvailabilityRecordKind(StrEnum):
    """The two configuration payloads represented by one version table."""

    OPENING_RULE = "opening_rule"
    DISCLOSURE_POLICY = "disclosure_policy"


class FinancialAvailabilityOwnerEventAction(StrEnum):
    """Append-only local lifecycle actions for one exact configuration row."""

    APPLY = "apply"
    REVOKE = "revoke"


def _token(value: object, name: str, *, maximum: int = 200) -> None:
    """Validate one bounded, trimmed, whitespace-free selector."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _text(value: object, name: str, *, maximum: int) -> None:
    """Validate one bounded trimmed text field which may contain spaces."""

    if type(value) is not str or not value or value.strip() != value or len(value) > maximum:
        raise ValueError(f"{name} must be bounded nonempty text")


def _utc(value: object, name: str) -> datetime:
    """Require a representable UTC instant without inventing its value."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{name} must be an aware UTC datetime")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must already be UTC")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} is not representable in UTC") from error


def _utc_iso(value: datetime, name: str) -> str:
    """Return a canonical UTC timestamp with fixed microsecond precision."""

    return _utc(value, name).isoformat(timespec="microseconds")


def _sha256(value: object, name: str) -> None:
    """Require one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be lowercase SHA-256")


def _canonical_sha256(domain: bytes, payload: dict[str, object]) -> str:
    """Hash one closed JSON object with a stable UTF-8 encoding."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()


def _date_evidence_payload(evidence: StatutorySourceDateEvidence) -> dict[str, str | None]:
    """Serialize statutory date precision without converting date-only values."""

    evidence.__post_init__()
    if evidence.precision.value == "date":
        value = evidence.date_value.isoformat() if evidence.date_value is not None else None
        instant = None
    elif evidence.precision.value == "instant":
        value = None
        instant = (
            _utc_iso(evidence.instant_value, "source date instant")
            if evidence.instant_value is not None
            else None
        )
    else:
        value = None
        instant = None
    return {"precision": evidence.precision.value, "date_value": value, "instant_value": instant}


@dataclass(frozen=True, slots=True)
class StatutorySourceCaptureReference:
    """Exact native revision/capture identity and distinct source clocks.

    The Infrastructure reader must derive ``first_seen_at`` from actual
    retained captures visible at the requested cutoff, load both database
    ``recorded_at`` values, and re-read the exact body bytes. This value alone
    authenticates none of those claims.
    """

    issuer: str
    document_id: str
    source_version: str
    title: str
    legal_number: str
    source_revision_sha256: str
    capture_id: UUID
    capture_content_type: str
    body_reference: str
    canonical_url: str
    body_sha256: str
    body_size_bytes: int
    publication_date: StatutorySourceDateEvidence
    source_effective_date: StatutorySourceDateEvidence
    first_seen_at: datetime
    capture_observed_at: datetime
    revision_recorded_at: datetime
    capture_recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate exact native identity and preserve source date precision."""

        for name, maximum in (
            ("issuer", 240),
            ("document_id", 240),
            ("source_version", 120),
            ("title", 1000),
            ("legal_number", 240),
        ):
            _text(getattr(self, name), name, maximum=maximum)
        _text(self.canonical_url, "canonical_url", maximum=4096)
        _text(self.capture_content_type, "capture_content_type", maximum=200)
        _text(self.body_reference, "body_reference", maximum=1024)
        parsed = urlsplit(self.canonical_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("canonical_url must be an exact HTTPS source URI")
        if type(self.capture_id) is not UUID:
            raise ValueError("capture_id must be a UUID")
        _sha256(self.body_sha256, "body_sha256")
        _sha256(self.source_revision_sha256, "source_revision_sha256")
        if type(self.body_size_bytes) is not int or self.body_size_bytes <= 0:
            raise ValueError("body_size_bytes must be a positive exact integer")
        for name in ("publication_date", "source_effective_date"):
            if type(getattr(self, name)) is not StatutorySourceDateEvidence:
                raise ValueError(f"{name} must retain exact source date precision")
        revision = StatutorySourceDocumentRevision(
            document_id=self.document_id,
            source_version=self.source_version,
            canonical_url=self.canonical_url,
            issuer=self.issuer,
            title=self.title,
            legal_number=self.legal_number,
            publication_date=self.publication_date,
            effective_date=self.source_effective_date,
            body_sha256=self.body_sha256,
            body_size_bytes=self.body_size_bytes,
        )
        if revision.source_revision_sha256 != self.source_revision_sha256:
            raise ValueError("source revision hash differs from exact native facts")
        first_seen = _utc(self.first_seen_at, "first_seen_at")
        captured = _utc(self.capture_observed_at, "capture_observed_at")
        revision_recorded = _utc(self.revision_recorded_at, "revision_recorded_at")
        capture_recorded = _utc(self.capture_recorded_at, "capture_recorded_at")
        if not first_seen <= captured <= capture_recorded:
            raise ValueError("source observation clocks are not ordered")
        if revision_recorded > capture_recorded:
            raise ValueError("revision record postdates the selected capture record")

    def to_payload(self) -> dict[str, object]:
        """Return exact source revision, capture, and database-clock identity."""

        self.__post_init__()
        return {
            "issuer": self.issuer,
            "document_id": self.document_id,
            "source_version": self.source_version,
            "title": self.title,
            "legal_number": self.legal_number,
            "source_revision_sha256": self.source_revision_sha256,
            "capture_id": str(self.capture_id),
            "capture_content_type": self.capture_content_type,
            "body_reference": self.body_reference,
            "canonical_url": self.canonical_url,
            "body_sha256": self.body_sha256,
            "body_size_bytes": self.body_size_bytes,
            "publication_date": _date_evidence_payload(self.publication_date),
            "source_effective_date": _date_evidence_payload(self.source_effective_date),
            "first_seen_at": _utc_iso(self.first_seen_at, "first_seen_at"),
            "capture_observed_at": _utc_iso(self.capture_observed_at, "capture_observed_at"),
            "revision_recorded_at": _utc_iso(self.revision_recorded_at, "revision_recorded_at"),
            "capture_recorded_at": _utc_iso(self.capture_recorded_at, "capture_recorded_at"),
        }


@dataclass(frozen=True, slots=True)
class ExchangeSessionOpeningRuleProposal:
    """Explicit rule configuration before the actual Owner apply event.

    This proposal has no ``approved_at``. The applied rule hash is created
    only after the local apply event supplies its actual server ``occurred_at``.
    """

    exchange: str
    phase: ExchangeSessionOpeningPhase
    rule_version: str
    source_uri: str
    source_body_sha256: str
    effective_start: date
    effective_end: date
    timezone_name: str
    local_open_time: time
    first_seen_at: datetime
    source_recorded_at: datetime

    def __post_init__(self) -> None:
        """Validate explicit source, phase, date range and wall-clock fields."""

        _token(self.exchange, "exchange", maximum=32)
        try:
            supported = exchange_calendar_publication_key(self.exchange)
        except (TypeError, ValueError) as error:
            raise ValueError("exchange is not supported by the formal calendar contract") from error
        if not supported:
            raise ValueError("exchange is not supported by the formal calendar contract")
        if type(self.phase) is not ExchangeSessionOpeningPhase:
            raise ValueError("opening phase must be explicitly selected")
        if (
            type(self.rule_version) is not str
            or _RULE_VERSION_RE.fullmatch(self.rule_version) is None
        ):
            raise ValueError("rule_version is invalid")
        _text(self.source_uri, "source_uri", maximum=4096)
        parsed = urlsplit(self.source_uri)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("source_uri must be an exact HTTPS URI")
        _sha256(self.source_body_sha256, "source_body_sha256")
        if type(self.effective_start) is not date or type(self.effective_end) is not date:
            raise ValueError("rule effective bounds must be exact dates")
        if self.effective_start > self.effective_end:
            raise ValueError("rule effective range is inverted")
        _text(self.timezone_name, "timezone_name", maximum=128)
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("timezone_name is unknown") from error
        if (
            type(self.local_open_time) is not time
            or self.local_open_time.tzinfo is not None
            or self.local_open_time.fold != 0
        ):
            raise ValueError("local_open_time must be an explicit unambiguous wall clock")
        first_seen = _utc(self.first_seen_at, "first_seen_at")
        source_recorded = _utc(self.source_recorded_at, "source_recorded_at")
        if first_seen > source_recorded:
            raise ValueError("source observation clocks are not ordered")

    def to_payload(self) -> dict[str, object]:
        """Return the closed proposal fields without an approval timestamp."""

        self.__post_init__()
        return {
            "schema": "data_center.exchange-session-opening-rule-proposal.v1",
            "exchange": self.exchange,
            "phase": self.phase.value,
            "rule_version": self.rule_version,
            "source_uri": self.source_uri,
            "source_body_sha256": self.source_body_sha256,
            "effective_start": self.effective_start.isoformat(),
            "effective_end": self.effective_end.isoformat(),
            "timezone_name": self.timezone_name,
            "local_open_time": self.local_open_time.isoformat(),
            "first_seen_at": _utc_iso(self.first_seen_at, "first_seen_at"),
            "source_recorded_at": _utc_iso(self.source_recorded_at, "source_recorded_at"),
        }

    @property
    def proposal_sha256(self) -> str:
        """Return the distinct content identity of this not-yet-applied proposal."""

        return _canonical_sha256(_RULE_PROPOSAL_HASH_DOMAIN, self.to_payload())

    def materialize_applied_rule(
        self, *, recorded_at: datetime, approved_at: datetime
    ) -> ExchangeSessionOpeningRule:
        """Bind database row and real apply-event clocks to the existing rule value."""

        row_recorded = _utc(recorded_at, "recorded_at")
        approval_clock = _utc(approved_at, "approved_at")
        if self.source_recorded_at > row_recorded:
            raise ValueError("rule row predates its source record")
        if approval_clock < row_recorded:
            raise ValueError("rule cannot be applied before its configuration row")
        payload = {
            "exchange": self.exchange,
            "phase": self.phase.value,
            "rule_version": self.rule_version,
            "source_uri": self.source_uri,
            "source_body_sha256": self.source_body_sha256,
            "effective_start": self.effective_start.isoformat(),
            "effective_end": self.effective_end.isoformat(),
            "timezone_name": self.timezone_name,
            "local_open_time": self.local_open_time.isoformat(),
            # Preserve the existing v3 rule codec's exact isoformat bytes.
            "first_seen_at": self.first_seen_at.isoformat(),
            "recorded_at": row_recorded.isoformat(),
            "approved_at": approval_clock.isoformat(),
        }
        return ExchangeSessionOpeningRule(
            exchange=self.exchange,
            phase=self.phase,
            rule_version=self.rule_version,
            source_uri=self.source_uri,
            source_body_sha256=self.source_body_sha256,
            effective_start=self.effective_start,
            effective_end=self.effective_end,
            timezone_name=self.timezone_name,
            local_open_time=self.local_open_time,
            first_seen_at=_utc(self.first_seen_at, "first_seen_at"),
            recorded_at=row_recorded,
            approved_at=approval_clock,
            rule_sha256=exchange_session_opening_rule_sha256(payload),
        )


FinancialAvailabilityContent: TypeAlias = (
    ExchangeSessionOpeningRuleProposal | FinancialDisclosureAvailabilityPolicy
)


@dataclass(frozen=True, slots=True)
class FinancialAvailabilityGovernanceRecord:
    """One immutable versioned configuration row with no mutable active flag."""

    record_id: str
    record_version: str
    exchange: str
    kind: FinancialAvailabilityRecordKind
    content: FinancialAvailabilityContent
    recorded_at: datetime
    source: StatutorySourceCaptureReference | None = None

    def __post_init__(self) -> None:
        """Bind one exact record payload to its record key and source identity."""

        _token(self.record_id, "record_id")
        _token(self.record_version, "record_version")
        _token(self.exchange, "exchange", maximum=32)
        if type(self.kind) is not FinancialAvailabilityRecordKind:
            raise ValueError("kind must be an exact financial availability record kind")
        try:
            supported_exchange = exchange_calendar_publication_key(self.exchange)
        except (TypeError, ValueError) as error:
            raise ValueError("exchange is not supported by the formal calendar contract") from error
        if not supported_exchange:
            raise ValueError("exchange is not supported by the formal calendar contract")
        row_recorded = _utc(self.recorded_at, "recorded_at")
        if self.kind is FinancialAvailabilityRecordKind.OPENING_RULE:
            if type(self.content) is not ExchangeSessionOpeningRuleProposal:
                raise ValueError("opening_rule requires an unapplied rule proposal")
            if type(self.source) is not StatutorySourceCaptureReference:
                raise ValueError("opening_rule requires an exact retained source capture")
            proposal = self.content
            source = self.source
            proposal.__post_init__()
            source.__post_init__()
            if (
                proposal.rule_version != self.record_version
                or proposal.exchange != self.exchange
                or proposal.source_uri != source.canonical_url
                or proposal.source_body_sha256 != source.body_sha256
                or proposal.first_seen_at != source.first_seen_at
                or proposal.source_recorded_at != source.revision_recorded_at
                or source.capture_recorded_at > row_recorded
            ):
                raise ValueError("opening rule proposal differs from exact source/record clocks")
            return

        if type(self.content) is not FinancialDisclosureAvailabilityPolicy:
            raise ValueError("disclosure_policy requires the exact typed policy")
        if self.source is not None:
            raise ValueError("disclosure policy cannot claim an unrelated source capture")
        policy = self.content
        policy.__post_init__()
        if (
            policy.policy_id != self.record_id
            or policy.policy_version != self.record_version
            or policy.exchange != self.exchange
            or policy.recorded_at != row_recorded
        ):
            raise ValueError("disclosure policy differs from its record identity/knowledge clock")

    def to_payload(self) -> dict[str, object]:
        """Return the full closed config-row payload, including exact source identity."""

        self.__post_init__()
        content: dict[str, object]
        if type(self.content) is ExchangeSessionOpeningRuleProposal:
            content = self.content.to_payload()
        elif type(self.content) is FinancialDisclosureAvailabilityPolicy:
            content = self.content.to_dict()
        else:
            raise ValueError("financial availability record content is unsupported")
        return {
            "schema": "data_center.financial-availability-record.v1",
            "record_id": self.record_id,
            "record_version": self.record_version,
            "exchange": self.exchange,
            "kind": self.kind.value,
            "recorded_at": _utc_iso(self.recorded_at, "recorded_at"),
            "content": content,
            "source": self.source.to_payload() if self.source is not None else None,
        }

    @property
    def content_sha256(self) -> str:
        """Return the immutable row digest, binding record and exact source keys."""

        return _canonical_sha256(_GOVERNANCE_RECORD_HASH_DOMAIN, self.to_payload())

    def resulting_content_sha256(self, *, approved_at: datetime) -> str:
        """Return the hash of the approved rule or exact policy content."""

        self.__post_init__()
        if type(self.content) is ExchangeSessionOpeningRuleProposal:
            return self.content.materialize_applied_rule(
                recorded_at=self.recorded_at,
                approved_at=approved_at,
            ).rule_sha256
        if type(self.content) is FinancialDisclosureAvailabilityPolicy:
            return self.content.policy_sha256
        raise ValueError("financial availability record content is unsupported")


@dataclass(frozen=True, slots=True)
class FinancialAvailabilityOwnerEventIdentity:
    """One local Owner apply/revoke event linked to a real User and Permission.

    The database reader must verify these fields against FK rows and recompute
    ``event_sha256``. This is not a SystemAudit event, outbox receipt, or
    standalone proof that Django permission checks occurred.
    """

    action: FinancialAvailabilityOwnerEventAction
    event_id: UUID
    event_sha256: str
    record_id: str
    record_version: str
    record_content_sha256: str
    resulting_content_sha256: str
    actor_user_id: int
    permission_id: int
    permission_app_label: str
    permission_codename: str
    permission_verified_at: datetime
    occurred_at: datetime
    recorded_at: datetime
    reason: str
    predecessor_apply_event_id: UUID | None = None
    predecessor_apply_event_sha256: str | None = None

    def __post_init__(self) -> None:
        """Validate event identity, server clocks, and append-only linkage."""

        if type(self.action) is not FinancialAvailabilityOwnerEventAction:
            raise ValueError("action must be an exact C2 owner-event action")
        if type(self.event_id) is not UUID:
            raise ValueError("event_id must be a UUID")
        _sha256(self.event_sha256, "event_sha256")
        _token(self.record_id, "record_id")
        _token(self.record_version, "record_version")
        _sha256(self.record_content_sha256, "record_content_sha256")
        _sha256(self.resulting_content_sha256, "resulting_content_sha256")
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be a positive exact User ID")
        if type(self.permission_id) is not int or self.permission_id <= 0:
            raise ValueError("permission_id must be a positive exact Permission ID")
        if (
            self.permission_app_label != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL
            or self.permission_codename != FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME
        ):
            raise ValueError("permission identity is not the dedicated C2 permission")
        verified = _utc(self.permission_verified_at, "permission_verified_at")
        occurred = _utc(self.occurred_at, "occurred_at")
        recorded = _utc(self.recorded_at, "recorded_at")
        _text(self.reason, "reason", maximum=1000)
        if not verified <= occurred <= recorded:
            raise ValueError("Owner event clocks are not ordered")
        if self.action is FinancialAvailabilityOwnerEventAction.APPLY:
            if (
                self.predecessor_apply_event_id is not None
                or self.predecessor_apply_event_sha256 is not None
            ):
                raise ValueError("apply event cannot bind a predecessor apply")
        elif (
            type(self.predecessor_apply_event_id) is not UUID
            or self.predecessor_apply_event_sha256 is None
        ):
            raise ValueError("revoke event must bind the exact apply event")
        if self.predecessor_apply_event_sha256 is not None:
            _sha256(self.predecessor_apply_event_sha256, "predecessor_apply_event_sha256")
        if self.event_sha256 != self.computed_event_sha256():
            raise ValueError("Owner event hash differs from its exact content")

    @classmethod
    def create(
        cls,
        *,
        action: FinancialAvailabilityOwnerEventAction,
        event_id: UUID,
        record: FinancialAvailabilityGovernanceRecord,
        resulting_content_sha256: str,
        actor_user_id: int,
        permission_id: int,
        permission_verified_at: datetime,
        occurred_at: datetime,
        recorded_at: datetime,
        reason: str,
        predecessor_apply_event_id: UUID | None = None,
        predecessor_apply_event_sha256: str | None = None,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        """Create an exact local event after DB actor and clocks are verified."""

        if type(action) is not FinancialAvailabilityOwnerEventAction:
            raise ValueError("action must be an exact C2 owner-event action")
        if type(event_id) is not UUID:
            raise ValueError("event_id must be a UUID")
        if type(record) is not FinancialAvailabilityGovernanceRecord:
            raise ValueError("record must be an exact C2 governance record")
        record.__post_init__()
        payload = cls._hash_payload(
            action=action,
            event_id=event_id,
            record_id=record.record_id,
            record_version=record.record_version,
            record_content_sha256=record.content_sha256,
            resulting_content_sha256=resulting_content_sha256,
            actor_user_id=actor_user_id,
            permission_id=permission_id,
            permission_app_label=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL,
            permission_verified_at=permission_verified_at,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            reason=reason,
            predecessor_apply_event_id=predecessor_apply_event_id,
            predecessor_apply_event_sha256=predecessor_apply_event_sha256,
        )
        digest = _canonical_sha256(_OWNER_EVENT_HASH_DOMAIN, payload)
        return cls(
            action=action,
            event_id=event_id,
            event_sha256=digest,
            record_id=record.record_id,
            record_version=record.record_version,
            record_content_sha256=record.content_sha256,
            resulting_content_sha256=resulting_content_sha256,
            actor_user_id=actor_user_id,
            permission_id=permission_id,
            permission_app_label=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_APP_LABEL,
            permission_codename=FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
            permission_verified_at=permission_verified_at,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            reason=reason,
            predecessor_apply_event_id=predecessor_apply_event_id,
            predecessor_apply_event_sha256=predecessor_apply_event_sha256,
        )

    @property
    def actor_id(self) -> str:
        """Return the canonical Django User identity used by a v3 binding."""

        self.__post_init__()
        return f"django-user:{self.actor_user_id}"

    def is_knowable_at(self, known_at: datetime) -> bool:
        """Return whether both event clocks precede the explicit UTC cutoff."""

        cutoff = _utc(known_at, "known_at")
        self.__post_init__()
        return max(self.recorded_at, self.occurred_at) <= cutoff

    def computed_event_sha256(self) -> str:
        """Recompute event identity from every immutable lifecycle field."""

        return _canonical_sha256(
            _OWNER_EVENT_HASH_DOMAIN,
            self._hash_payload(
                action=self.action,
                event_id=self.event_id,
                record_id=self.record_id,
                record_version=self.record_version,
                record_content_sha256=self.record_content_sha256,
                resulting_content_sha256=self.resulting_content_sha256,
                actor_user_id=self.actor_user_id,
                permission_id=self.permission_id,
                permission_app_label=self.permission_app_label,
                permission_verified_at=self.permission_verified_at,
                occurred_at=self.occurred_at,
                recorded_at=self.recorded_at,
                reason=self.reason,
                predecessor_apply_event_id=self.predecessor_apply_event_id,
                predecessor_apply_event_sha256=self.predecessor_apply_event_sha256,
            ),
        )

    @staticmethod
    def _hash_payload(
        *,
        action: FinancialAvailabilityOwnerEventAction,
        event_id: UUID,
        record_id: str,
        record_version: str,
        record_content_sha256: str,
        resulting_content_sha256: str,
        actor_user_id: int,
        permission_id: int,
        permission_app_label: str,
        permission_verified_at: datetime,
        occurred_at: datetime,
        recorded_at: datetime,
        reason: str,
        predecessor_apply_event_id: UUID | None,
        predecessor_apply_event_sha256: str | None,
    ) -> dict[str, object]:
        """Build the closed canonical hash fields without a circular event ref."""

        return {
            "schema": "data_center.financial-availability-owner-event.v1",
            "action": action.value,
            "event_id": str(event_id),
            "record_id": record_id,
            "record_version": record_version,
            "record_content_sha256": record_content_sha256,
            "resulting_content_sha256": resulting_content_sha256,
            "actor_user_id": actor_user_id,
            "permission_id": permission_id,
            "permission_app_label": permission_app_label,
            "permission_codename": FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME,
            "permission_verified_at": _utc_iso(permission_verified_at, "permission_verified_at"),
            "occurred_at": _utc_iso(occurred_at, "occurred_at"),
            "recorded_at": _utc_iso(recorded_at, "recorded_at"),
            "reason": reason,
            "predecessor_apply_event_id": (
                str(predecessor_apply_event_id) if predecessor_apply_event_id is not None else None
            ),
            "predecessor_apply_event_sha256": predecessor_apply_event_sha256,
        }


def resolve_financial_availability_owner_apply(
    record: FinancialAvailabilityGovernanceRecord,
    events: tuple[FinancialAvailabilityOwnerEventIdentity, ...],
    *,
    known_at: datetime,
    server_now: datetime,
) -> FinancialAvailabilityOwnerEventIdentity | None:
    """Return one applied event visible at cutoff, or fail closed on corruption.

    ``server_now`` must be independently sampled from the database. Later
    append-only revoke events do not change an earlier historical cutoff, but
    duplicate or malformed event history blocks every cutoff.
    """

    record.__post_init__()
    cutoff = _utc(known_at, "known_at")
    now = _utc(server_now, "server_now")
    if cutoff > now:
        raise ValueError("known_at cannot be later than database server time")
    if record.recorded_at > now:
        raise ValueError("configuration record is future-dated")
    if record.recorded_at > cutoff:
        return None
    if type(events) is not tuple:
        raise ValueError("Owner event history must be a complete immutable tuple")
    if not events:
        return None
    if any(type(event) is not FinancialAvailabilityOwnerEventIdentity for event in events):
        raise ValueError("Owner event history contains an untyped item")
    event_ids = tuple(event.event_id for event in events)
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("Owner event history contains a duplicate event ID")
    for event in events:
        event.__post_init__()
        if (
            event.record_id != record.record_id
            or event.record_version != record.record_version
            or event.record_content_sha256 != record.content_sha256
        ):
            raise ValueError("Owner event differs from the exact configuration result")
        if max(event.occurred_at, event.recorded_at, event.permission_verified_at) > now:
            raise ValueError("Owner event contains a future knowledge clock")
    apply_events = tuple(
        event for event in events if event.action is FinancialAvailabilityOwnerEventAction.APPLY
    )
    revoke_events = tuple(
        event for event in events if event.action is FinancialAvailabilityOwnerEventAction.REVOKE
    )
    if len(apply_events) != 1 or len(revoke_events) > 1:
        raise ValueError("configuration requires one apply and at most one revoke event")
    apply_event = apply_events[0]
    expected_result_hash = record.resulting_content_sha256(approved_at=apply_event.occurred_at)
    if (
        apply_event.resulting_content_sha256 != expected_result_hash
        or apply_event.occurred_at < record.recorded_at
        or apply_event.recorded_at < record.recorded_at
    ):
        raise ValueError("apply event result hash differs from actual apply time")
    if revoke_events:
        revoke = revoke_events[0]
        if (
            revoke.predecessor_apply_event_id != apply_event.event_id
            or revoke.predecessor_apply_event_sha256 != apply_event.event_sha256
            or revoke.resulting_content_sha256 != apply_event.resulting_content_sha256
            or revoke.occurred_at < apply_event.occurred_at
            or revoke.recorded_at < apply_event.recorded_at
        ):
            raise ValueError("revoke event does not append to the exact apply event")
    if not apply_event.is_knowable_at(cutoff):
        return None
    if revoke_events and revoke_events[0].is_knowable_at(cutoff):
        return None
    return apply_event


__all__ = [
    "ExchangeSessionOpeningRuleProposal",
    "FINANCIAL_AVAILABILITY_GOVERNANCE_PERMISSION_CODENAME",
    "FinancialAvailabilityContent",
    "FinancialAvailabilityGovernanceRecord",
    "FinancialAvailabilityOwnerEventAction",
    "FinancialAvailabilityOwnerEventIdentity",
    "FinancialAvailabilityRecordKind",
    "StatutorySourceCaptureReference",
    "resolve_financial_availability_owner_apply",
]
