"""Source-qualified Audit/Outbox observations for disclosure fact batches."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Protocol

from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxWriter,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)
from core.exceptions import DataValidationError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSET_RE = re.compile(r"^[0-9]{6}\.SZ$")
_EVENT_VERSION = "1"


class SecurityDisclosureAuditConflict(DataValidationError):
    """An existing Audit identity does not represent the exact source batch."""

    default_message = "Disclosure Audit identity conflicts with retained source evidence."
    default_code = "SECURITY_DISCLOSURE_AUDIT_CONFLICT"
    default_status_code = 409


class SecurityDisclosureAuditUnavailable(DataValidationError):
    """The required scoped Audit/Outbox capability is unavailable."""

    default_message = "Required disclosure Audit/Outbox capability is unavailable."
    default_code = "SECURITY_DISCLOSURE_AUDIT_UNAVAILABLE"
    default_status_code = 503


class SecurityDisclosureAuditDisposition(StrEnum):
    """Whether this observation first created or reused its exact Audit winner."""

    STORED = "stored"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class SecurityDisclosureFactEvidence:
    """Source identity and immutable hashes for one persisted disclosure revision."""

    source_event_id: str
    source_revision_id: str
    content_hash: str
    source_body_sha256: str

    def __post_init__(self) -> None:
        for field_name in ("source_event_id", "source_revision_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value or len(value) > 200:
                raise ValueError(f"{field_name} must be bounded non-empty text")
        for field_name in ("content_hash", "source_body_sha256"):
            if type(getattr(self, field_name)) is not str or not _SHA256_RE.fullmatch(
                getattr(self, field_name)
            ):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if self.source_revision_id != f"sha256:{self.source_body_sha256}":
            raise ValueError("source revision must bind the retained source body hash")


@dataclass(frozen=True, slots=True)
class SecurityDisclosureAuditObservation:
    """Immutable, source-bound summary of one fully captured SZSE window."""

    source: str
    exchange: str
    asset_code: str
    start_on: date
    end_on: date
    first_observed_at: datetime
    verified_at: datetime
    announcement_count: int
    coverage_manifest_sha256: str
    source_manifest_sha256: str
    first_pass_page_body_sha256: tuple[str, ...]
    second_pass_page_body_sha256: tuple[str, ...]
    facts: tuple[SecurityDisclosureFactEvidence, ...]
    recorded_at: datetime
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        if self.source != "szse_official" or self.exchange != "SZSE":
            raise ValueError("disclosure Audit currently requires the official SZSE source")
        if type(self.asset_code) is not str or not _ASSET_RE.fullmatch(self.asset_code):
            raise ValueError("asset_code must be a canonical SZSE security code")
        for field_name in ("start_on", "end_on"):
            value = getattr(self, field_name)
            if type(value) is not date:
                raise ValueError(f"{field_name} must preserve date precision")
        if self.start_on > self.end_on:
            raise ValueError("disclosure window dates are reversed")
        for field_name in ("first_observed_at", "verified_at", "recorded_at"):
            value = getattr(self, field_name)
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if not self.first_observed_at <= self.verified_at <= self.recorded_at:
            raise ValueError("disclosure observation, verification, and record clocks are invalid")
        if type(self.announcement_count) is not int or self.announcement_count < 0:
            raise ValueError("announcement_count must be a non-negative integer")
        if type(self.facts) is not tuple or any(
            type(item) is not SecurityDisclosureFactEvidence for item in self.facts
        ):
            raise ValueError("facts must be a tuple of exact disclosure evidence")
        if len(self.facts) > self.announcement_count:
            raise ValueError("fact count cannot exceed listed announcement count")
        if len({item.source_event_id for item in self.facts}) != len(self.facts):
            raise ValueError("source event identities must be unique in one batch")
        for field_name in (
            "coverage_manifest_sha256",
            "source_manifest_sha256",
        ):
            if type(getattr(self, field_name)) is not str or not _SHA256_RE.fullmatch(
                getattr(self, field_name)
            ):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        if (
            type(self.first_pass_page_body_sha256) is not tuple
            or type(self.second_pass_page_body_sha256) is not tuple
            or not self.first_pass_page_body_sha256
            or len(self.first_pass_page_body_sha256) != len(self.second_pass_page_body_sha256)
        ):
            raise ValueError("both complete listing-pass hash sets are required")
        for digest in (*self.first_pass_page_body_sha256, *self.second_pass_page_body_sha256):
            if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
                raise ValueError("listing page hashes must be lowercase SHA-256 digests")
        if self.scope is not None and type(self.scope) is not AuditScopeRef:
            raise TypeError("scope must be an exact AuditScopeRef or None")

    @property
    def batch_identity(self) -> str:
        """Return a stable batch hash over the exact listing and selected PDF facts."""

        payload = _stable_detail(self)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SecurityDisclosureAuditAppendResult:
    """Exact event/outbox winner and whether this call first stored it."""

    disposition: SecurityDisclosureAuditDisposition
    commit: SystemAuditEventOutboxCommit

    def __post_init__(self) -> None:
        if type(self.disposition) is not SecurityDisclosureAuditDisposition:
            raise ValueError("disposition must be a recognized Audit append outcome")
        if type(self.commit) is not SystemAuditEventOutboxCommit:
            raise ValueError("commit must contain the exact Audit and Outbox winner")


class SecurityDisclosureAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Scoped Audit writer sharing one transaction with source-fact writes."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by event and outbox storage."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the same-alias transaction containing facts and event/outbox writes."""

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Read the exact prior event identity at a bounded timestamp."""

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Read the scoped stream predecessor used for append CAS."""

    def list_events(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[SystemAuditEvent, ...]:
        """Read the scoped immutable stream prefix for prior-fact proof."""


class SecurityDisclosureAuditScopeProvider(Protocol):
    """Resolve the current server-issued owner/tenant scope for a source event."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return the exact authoritative scope at ``as_of``."""


class AppendSecurityDisclosureAuditObservationUseCase:
    """Append one source-qualified disclosure batch through unified Audit/Outbox."""

    __slots__ = ("_writer", "_scope_provider")

    def __init__(
        self,
        writer: SecurityDisclosureAuditEventOutboxWriter,
        scope_provider: SecurityDisclosureAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the exact alias used by this Audit writer."""

        return self._writer.database_alias

    def preflight(self, *, as_of: datetime) -> AuditScopeRef:
        """Resolve current server-issued scope before external source capture."""

        _require_aware(as_of, "as_of")
        scope = self._scope_provider.get_scope(as_of=as_of)
        if type(scope) is not AuditScopeRef:
            raise SecurityDisclosureAuditUnavailable(
                "The disclosure Audit scope provider returned an invalid scope."
            )
        return scope

    def atomic(self) -> AbstractContextManager[None]:
        """Open the canonical Audit/Outbox transaction for the entire source batch."""

        return self._writer.atomic()

    def find_exact_winner(
        self,
        observation: SecurityDisclosureAuditObservation,
        *,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Find an exact batch Audit event and reject reused IDs with changed evidence."""

        _require_observation(observation)
        _require_aware(as_of, "as_of")
        if type(scope) is not AuditScopeRef:
            raise SecurityDisclosureAuditUnavailable("A current Audit scope is required.")
        current_scope = self.preflight(as_of=as_of)
        if current_scope != scope:
            raise SecurityDisclosureAuditUnavailable("Disclosure Audit scope changed.")
        event = self._writer.get_winner(
            event_id=_event_id(observation),
            event_version=_EVENT_VERSION,
            as_of=as_of,
        )
        if event is None:
            return None
        _validate_existing_event(event, observation, scope=scope)
        return event

    def assert_previously_audited_facts(
        self,
        observation: SecurityDisclosureAuditObservation,
        *,
        facts: tuple[SecurityDisclosureFactEvidence, ...],
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> None:
        """Require every duplicate source revision to appear in canonical prior Audit."""

        _require_observation(observation)
        _require_aware(as_of, "as_of")
        if type(scope) is not AuditScopeRef:
            raise SecurityDisclosureAuditUnavailable("A current Audit scope is required.")
        current_scope = self.preflight(as_of=as_of)
        if current_scope != scope:
            raise SecurityDisclosureAuditUnavailable("Disclosure Audit scope changed.")
        if type(facts) is not tuple or any(
            type(item) is not SecurityDisclosureFactEvidence for item in facts
        ):
            raise SecurityDisclosureAuditConflict("Duplicate fact evidence is invalid.")
        expected_facts = set(observation.facts)
        if not set(facts).issubset(expected_facts):
            raise SecurityDisclosureAuditConflict(
                "Duplicate fact evidence falls outside the source batch."
            )
        prior_events = self._writer.list_events(
            stream_id=_stream_id(observation),
            as_of=as_of,
            scope=scope,
        )
        previously_audited: set[SecurityDisclosureFactEvidence] = set()
        for event in prior_events:
            if event.event_type != "data.disclosure_fact.appended":
                raise SecurityDisclosureAuditConflict(
                    "Disclosure Audit stream contains an unexpected event type."
                )
            prior_observation = _observation_from_event(event, scope=scope)
            previously_audited.update(prior_observation.facts)
        if any(fact not in previously_audited for fact in facts):
            raise SecurityDisclosureAuditConflict(
                "A duplicate disclosure fact has no exact prior Audit evidence."
            )

    def execute_in_atomic_transaction(
        self,
        observation: SecurityDisclosureAuditObservation,
        *,
        scope: AuditScopeRef,
    ) -> SecurityDisclosureAuditAppendResult:
        """Append or replay while the enclosing Audit UOW owns the source transaction."""

        _require_observation(observation)
        if type(scope) is not AuditScopeRef:
            raise SecurityDisclosureAuditUnavailable("A current Audit scope is required.")
        current_scope = self.preflight(as_of=observation.recorded_at)
        if current_scope != scope:
            raise SecurityDisclosureAuditUnavailable("Disclosure Audit scope changed.")
        event_id = _event_id(observation)
        stream_id = _stream_id(observation)
        winner = self._writer.get_winner(
            event_id=event_id,
            event_version=_EVENT_VERSION,
            as_of=observation.recorded_at,
        )
        if winner is not None:
            _validate_existing_event(winner, observation, scope=scope)
            commit = self._writer.append_and_enqueue(
                winner,
                expected_predecessor_hash=winner.predecessor_hash,
                recorded_at=winner.recorded_at,
            )
            disposition = SecurityDisclosureAuditDisposition.DUPLICATE
        else:
            head = self._writer.get_current_head(
                stream_id=stream_id,
                as_of=observation.recorded_at,
                scope=scope,
            )
            sequence_no = head.sequence_no + 1 if head is not None else 1
            predecessor_hash = head.content_hash if head is not None else None
            scoped_observation = _with_scope(observation, scope)
            event = build_security_disclosure_fact_audit_event(
                scoped_observation,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            commit = self._writer.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
            if commit.event != event:
                raise SecurityDisclosureAuditConflict(
                    "The Audit writer substituted a disclosure event winner."
                )
            disposition = SecurityDisclosureAuditDisposition.STORED
        return SecurityDisclosureAuditAppendResult(disposition, commit)


def build_security_disclosure_fact_audit_event(
    observation: SecurityDisclosureAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build the canonical source-qualified `data.disclosure_fact.appended` event."""

    _require_observation(observation)
    if type(observation.scope) is not AuditScopeRef:
        raise SecurityDisclosureAuditUnavailable("A current Audit scope is required.")
    if type(sequence_no) is not int or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None and not _SHA256_RE.fullmatch(predecessor_hash):
        raise ValueError("predecessor_hash must be a lowercase SHA-256 digest")
    detail = _stable_detail(observation)
    batch_identity = observation.batch_identity
    evidence_refs = (
        AuditEvidenceRef(
            owner="data_center",
            artifact_type="szse_listing_coverage",
            artifact_id=observation.coverage_manifest_sha256,
            artifact_version="szse.announcement-window-coverage.v2",
            content_hash=observation.coverage_manifest_sha256,
        ),
        *tuple(
            AuditEvidenceRef(
                owner="data_center",
                artifact_type="szse_disclosure_pdf",
                artifact_id=fact.source_event_id,
                artifact_version=fact.source_revision_id,
                content_hash=fact.source_body_sha256,
            )
            for fact in sorted(observation.facts, key=lambda item: item.source_event_id)
        ),
    )
    return SystemAuditEvent.create(
        event_id=_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.disclosure_fact.appended",
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=("disclosure_fact_batch_appended",),
        occurred_at=observation.first_observed_at,
        recorded_at=observation.recorded_at,
        observed_at=observation.verified_at,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="security_disclosure_capture",
        source_surface="application",
        correlations=AuditCorrelations(evidence_ref=batch_identity),
        resource=AuditResourceRef(
            "security_disclosure_window",
            batch_identity,
            "szse.announcement-window-coverage.v2",
        ),
        dataset_key=observation.asset_code,
        provider_key=observation.source,
        capability="official_disclosure_listing",
        publication_id=None,
        evidence_refs=evidence_refs,
        detail_schema="data.disclosure_fact.appended.v1",
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"data.disclosure_fact.appended:{batch_identity}",
        scope=observation.scope,
    )


def _stable_detail(observation: SecurityDisclosureAuditObservation) -> dict[str, JSONValue]:
    """Return the stable evidence subset used for batch identity and replay checks."""

    return {
        "source": observation.source,
        "exchange": observation.exchange,
        "asset_code": observation.asset_code,
        "start_on": observation.start_on.isoformat(),
        "end_on": observation.end_on.isoformat(),
        "first_observed_at": _utc_text(observation.first_observed_at),
        "verified_at": _utc_text(observation.verified_at),
        "announcement_count": observation.announcement_count,
        "coverage_manifest_sha256": observation.coverage_manifest_sha256,
        "source_manifest_sha256": observation.source_manifest_sha256,
        "first_pass_page_body_sha256": list(observation.first_pass_page_body_sha256),
        "second_pass_page_body_sha256": list(observation.second_pass_page_body_sha256),
        "facts": [
            {
                "source_event_id": item.source_event_id,
                "source_revision_id": item.source_revision_id,
                "content_hash": item.content_hash,
                "source_body_sha256": item.source_body_sha256,
            }
            for item in sorted(observation.facts, key=lambda value: value.source_event_id)
        ],
    }


def _event_id(observation: SecurityDisclosureAuditObservation) -> str:
    return f"data-disclosure-{observation.batch_identity[:48]}"


def _stream_id(observation: SecurityDisclosureAuditObservation) -> str:
    return f"data.disclosure_fact:{observation.asset_code}"


def _with_scope(
    observation: SecurityDisclosureAuditObservation,
    scope: AuditScopeRef,
) -> SecurityDisclosureAuditObservation:
    return SecurityDisclosureAuditObservation(
        source=observation.source,
        exchange=observation.exchange,
        asset_code=observation.asset_code,
        start_on=observation.start_on,
        end_on=observation.end_on,
        first_observed_at=observation.first_observed_at,
        verified_at=observation.verified_at,
        announcement_count=observation.announcement_count,
        coverage_manifest_sha256=observation.coverage_manifest_sha256,
        source_manifest_sha256=observation.source_manifest_sha256,
        first_pass_page_body_sha256=observation.first_pass_page_body_sha256,
        second_pass_page_body_sha256=observation.second_pass_page_body_sha256,
        facts=observation.facts,
        recorded_at=observation.recorded_at,
        scope=scope,
    )


def _validate_existing_event(
    event: SystemAuditEvent,
    observation: SecurityDisclosureAuditObservation,
    *,
    scope: AuditScopeRef,
) -> None:
    """Require a stable same-scope winner for this exact batch identity."""

    try:
        persisted_observation = _observation_from_event(event, scope=scope)
    except (TypeError, ValueError, SecurityDisclosureAuditUnavailable) as error:
        raise SecurityDisclosureAuditConflict(
            "An existing disclosure Audit identity is not canonical."
        ) from error
    if persisted_observation.batch_identity != observation.batch_identity:
        raise SecurityDisclosureAuditConflict(
            "An existing disclosure Audit identity has different source evidence or scope."
        )


def _observation_from_event(
    event: SystemAuditEvent,
    *,
    scope: AuditScopeRef,
) -> SecurityDisclosureAuditObservation:
    """Restore and fully verify one prior disclosure event's canonical evidence."""

    if (
        type(event) is not SystemAuditEvent
        or type(scope) is not AuditScopeRef
        or event.scope != scope
        or event.observed_at is None
        or not isinstance(event.detail, Mapping)
        or set(event.detail)
        != {
            "source",
            "exchange",
            "asset_code",
            "start_on",
            "end_on",
            "first_observed_at",
            "verified_at",
            "announcement_count",
            "coverage_manifest_sha256",
            "source_manifest_sha256",
            "first_pass_page_body_sha256",
            "second_pass_page_body_sha256",
            "facts",
        }
    ):
        raise SecurityDisclosureAuditConflict("Prior disclosure Audit detail is malformed.")
    detail = event.detail
    facts_value = detail["facts"]
    if type(facts_value) is not list:
        raise SecurityDisclosureAuditConflict("Prior disclosure fact evidence is malformed.")
    facts: list[SecurityDisclosureFactEvidence] = []
    expected_fact_keys = {
        "source_event_id",
        "source_revision_id",
        "content_hash",
        "source_body_sha256",
    }
    for value in facts_value:
        if not isinstance(value, Mapping) or set(value) != expected_fact_keys:
            raise SecurityDisclosureAuditConflict("Prior disclosure fact evidence is malformed.")
        facts.append(
            SecurityDisclosureFactEvidence(
                source_event_id=_detail_text(value["source_event_id"], "source_event_id"),
                source_revision_id=_detail_text(value["source_revision_id"], "source_revision_id"),
                content_hash=_detail_text(value["content_hash"], "content_hash"),
                source_body_sha256=_detail_text(value["source_body_sha256"], "source_body_sha256"),
            )
        )
    observation = SecurityDisclosureAuditObservation(
        source=_detail_text(detail["source"], "source"),
        exchange=_detail_text(detail["exchange"], "exchange"),
        asset_code=_detail_text(detail["asset_code"], "asset_code"),
        start_on=_detail_date(detail["start_on"], "start_on"),
        end_on=_detail_date(detail["end_on"], "end_on"),
        first_observed_at=_parse_utc_text(detail["first_observed_at"], "first_observed_at"),
        verified_at=_parse_utc_text(detail["verified_at"], "verified_at"),
        announcement_count=_detail_int(detail["announcement_count"], "announcement_count"),
        coverage_manifest_sha256=_detail_text(
            detail["coverage_manifest_sha256"], "coverage_manifest_sha256"
        ),
        source_manifest_sha256=_detail_text(
            detail["source_manifest_sha256"], "source_manifest_sha256"
        ),
        first_pass_page_body_sha256=_detail_text_tuple(
            detail["first_pass_page_body_sha256"], "first_pass_page_body_sha256"
        ),
        second_pass_page_body_sha256=_detail_text_tuple(
            detail["second_pass_page_body_sha256"], "second_pass_page_body_sha256"
        ),
        facts=tuple(facts),
        recorded_at=event.recorded_at,
        scope=scope,
    )
    if (
        event.occurred_at != observation.first_observed_at
        or event.observed_at != observation.verified_at
    ):
        raise SecurityDisclosureAuditConflict(
            "Prior disclosure event clocks differ from its detail."
        )
    expected = build_security_disclosure_fact_audit_event(
        observation,
        sequence_no=event.sequence_no,
        predecessor_hash=event.predecessor_hash,
    )
    if expected != event:
        raise SecurityDisclosureAuditConflict("Prior disclosure Audit event is not canonical.")
    return observation


def _detail_text(value: JSONValue, field_name: str) -> str:
    if type(value) is not str:
        raise SecurityDisclosureAuditConflict(f"Prior Audit field {field_name} is not text.")
    return value


def _detail_int(value: JSONValue, field_name: str) -> int:
    if type(value) is not int:
        raise SecurityDisclosureAuditConflict(f"Prior Audit field {field_name} is not an integer.")
    return value


def _detail_text_tuple(value: JSONValue, field_name: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise SecurityDisclosureAuditConflict(f"Prior Audit field {field_name} is malformed.")
    return tuple(value)


def _detail_date(value: JSONValue, field_name: str) -> date:
    raw = _detail_text(value, field_name)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as error:
        raise SecurityDisclosureAuditConflict(
            f"Prior Audit field {field_name} is not an ISO date."
        ) from error
    if parsed.isoformat() != raw:
        raise SecurityDisclosureAuditConflict(f"Prior Audit field {field_name} is not canonical.")
    return parsed


def _parse_utc_text(value: JSONValue, field_name: str) -> datetime:
    raw = _detail_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise SecurityDisclosureAuditConflict(
            f"Prior Audit field {field_name} is not an ISO timestamp."
        ) from error
    if _utc_text(parsed) != raw:
        raise SecurityDisclosureAuditConflict(f"Prior Audit field {field_name} is not canonical.")
    return parsed


def _utc_text(value: datetime) -> str:
    _require_aware(value, "disclosure clock")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_observation(observation: SecurityDisclosureAuditObservation) -> None:
    if type(observation) is not SecurityDisclosureAuditObservation:
        raise SecurityDisclosureAuditConflict("Disclosure Audit observation is invalid.")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SecurityDisclosureAuditUnavailable(f"{field_name} must be timezone-aware.")


__all__ = [
    "AppendSecurityDisclosureAuditObservationUseCase",
    "SecurityDisclosureAuditAppendResult",
    "SecurityDisclosureAuditConflict",
    "SecurityDisclosureAuditDisposition",
    "SecurityDisclosureAuditEventOutboxWriter",
    "SecurityDisclosureAuditObservation",
    "SecurityDisclosureAuditScopeProvider",
    "SecurityDisclosureAuditUnavailable",
    "SecurityDisclosureFactEvidence",
    "build_security_disclosure_fact_audit_event",
]
