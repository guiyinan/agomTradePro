"""Canonical parent-run audit contract for Data Center reliability repairs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Final, Protocol
from uuid import UUID

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
from apps.data_center.application.sync_identity import SyncExecutionIdentity

_EVENT_VERSION: Final[str] = "1"
_IDENTITY_VERSION: Final[str] = "1"
_PARENT_DATASET_KEY: Final[str] = "decision.reliability.repair"
_PARENT_PROVIDER_KEY: Final[str] = "data-center-repair"
_ALLOWED_OUTCOMES: Final[frozenset[AuditOutcome]] = frozenset(
    {AuditOutcome.SUCCESS, AuditOutcome.PARTIAL, AuditOutcome.FAILED}
)
_ALLOWED_SECTION_STATUSES: Final[frozenset[str]] = frozenset(
    {"ready", "blocked", "failed", "skipped"}
)


def _require_text(value: object, field_name: str, *, maximum: int = 256) -> str:
    """Return one bounded non-blank string without changing its identity."""

    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-empty string")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Return one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _require_uuid(value: object, field_name: str) -> str:
    """Return canonical lowercase UUID text."""

    text = _require_text(value, field_name)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a canonical UUID") from error
    if str(parsed) != text.lower():
        raise ValueError(f"{field_name} must use canonical lowercase UUID text")
    return text


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class RepairPublicationEvidence:
    """Exact canonical publication produced by one child repair sync."""

    publication_id: str
    publication_version: str
    publication_hash: str
    dataset_key: str

    def __post_init__(self) -> None:
        _require_uuid(self.publication_id, "publication_id")
        _require_text(self.publication_version, "publication_version")
        _require_digest(self.publication_hash, "publication_hash")
        _require_text(self.dataset_key, "dataset_key", maximum=192)


@dataclass(frozen=True, slots=True)
class RepairSectionEvidence:
    """Sanitized outcome summary for one stable repair section."""

    section_key: str
    status: str
    must_not_use_for_decision: bool
    remaining_blocker_count: int

    def __post_init__(self) -> None:
        _require_text(self.section_key, "section_key", maximum=96)
        if self.status not in _ALLOWED_SECTION_STATUSES:
            raise ValueError("repair section status is not registered")
        if type(self.must_not_use_for_decision) is not bool:
            raise TypeError("must_not_use_for_decision must be a bool")
        if (
            not isinstance(self.remaining_blocker_count, int)
            or isinstance(self.remaining_blocker_count, bool)
            or self.remaining_blocker_count < 0
        ):
            raise ValueError("remaining_blocker_count must be a non-negative integer")
        if self.status == "ready" and (
            self.must_not_use_for_decision or self.remaining_blocker_count != 0
        ):
            raise ValueError("ready repair sections cannot retain blockers")
        if self.status in {"blocked", "failed"} and (
            not self.must_not_use_for_decision or self.remaining_blocker_count < 1
        ):
            raise ValueError("blocked or failed repair sections require blockers")


@dataclass(frozen=True, slots=True)
class DataRepairAuditObservation:
    """Immutable evidence that one canonical reliability-repair run finished."""

    identity: SyncExecutionIdentity
    target_date: date
    sections: tuple[RepairSectionEvidence, ...]
    publications: tuple[RepairPublicationEvidence, ...]
    outcome: AuditOutcome
    occurred_at: datetime
    recorded_at: datetime
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SyncExecutionIdentity):
            raise TypeError("identity must be a SyncExecutionIdentity")
        if self.identity.dataset_key != _PARENT_DATASET_KEY:
            raise ValueError("repair identity uses the wrong dataset")
        if self.identity.provider_name != _PARENT_PROVIDER_KEY:
            raise ValueError("repair identity uses the wrong provider")
        if not isinstance(self.target_date, date) or isinstance(self.target_date, datetime):
            raise TypeError("target_date must be a date")
        if not isinstance(self.sections, tuple) or not self.sections:
            raise ValueError("repair completion requires section evidence")
        if not all(isinstance(section, RepairSectionEvidence) for section in self.sections):
            raise TypeError("sections must contain RepairSectionEvidence values")
        section_keys = [section.section_key for section in self.sections]
        if len(set(section_keys)) != len(section_keys):
            raise ValueError("repair section evidence contains duplicate keys")
        if not isinstance(self.publications, tuple) or not all(
            isinstance(publication, RepairPublicationEvidence) for publication in self.publications
        ):
            raise TypeError("publications must contain RepairPublicationEvidence values")
        publication_ids = [publication.publication_id for publication in self.publications]
        if len(set(publication_ids)) != len(publication_ids):
            raise ValueError("repair publication evidence contains duplicate identities")
        if self.outcome not in _ALLOWED_OUTCOMES:
            raise ValueError("repair completion outcome is not registered")
        expected_outcome = _section_outcome(self.sections)
        if self.outcome is not expected_outcome:
            raise ValueError("repair outcome differs from its section evidence")
        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        if occurred_at > recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")

    @property
    def run_id(self) -> str:
        """Return the parent repair run identity."""

        return self.identity.run_id

    @property
    def ingested_run_id(self) -> str:
        """Return the parent repair ingestion identity."""

        return self.identity.ingested_run_id

    @property
    def dataset_key(self) -> str:
        """Return the parent repair dataset key."""

        return self.identity.dataset_key


def _section_outcome(sections: tuple[RepairSectionEvidence, ...]) -> AuditOutcome:
    """Derive the registered parent outcome from sanitized section summaries."""

    if any(section.status == "failed" for section in sections):
        return AuditOutcome.FAILED
    if any(section.must_not_use_for_decision for section in sections):
        return AuditOutcome.PARTIAL
    return AuditOutcome.SUCCESS


def _stable_event_id(observation: DataRepairAuditObservation) -> str:
    """Return one deterministic event identity for the immutable repair identity."""

    material = f"{observation.identity.identity_hash}|data.repair.completed"
    return f"data-repair-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:48]}"


def _stream_id(observation: DataRepairAuditObservation) -> str:
    """Return the stable repair-run ledger stream."""

    return f"data.repair:{observation.dataset_key}"


class DataRepairAuditScopeProvider(Protocol):
    """Resolve the authoritative scope for one repair completion."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataRepairAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical repair-completion event/outbox writer with exact replay."""

    @property
    def database_alias(self) -> str:
        """Return the database alias shared by event and outbox writes."""

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return an existing exact event identity at the PIT cutoff."""

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Return the scoped stream head used for predecessor CAS."""


def build_data_repair_audit_event(
    observation: DataRepairAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical repair-parent completion event."""

    if not isinstance(observation, DataRepairAuditObservation):
        raise TypeError("observation must be a DataRepairAuditObservation")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    sections = sorted(observation.sections, key=lambda item: item.section_key)
    publications = sorted(
        observation.publications,
        key=lambda item: (item.dataset_key, item.publication_id),
    )
    section_detail: list[JSONValue] = [
        {
            "section_key": section.section_key,
            "status": section.status,
            "must_not_use_for_decision": section.must_not_use_for_decision,
            "remaining_blocker_count": section.remaining_blocker_count,
        }
        for section in sections
    ]
    publication_detail: list[JSONValue] = [
        {
            "publication_id": publication.publication_id,
            "publication_version": publication.publication_version,
            "publication_hash": publication.publication_hash,
            "dataset_key": publication.dataset_key,
        }
        for publication in publications
    ]
    evidence_refs = (
        AuditEvidenceRef(
            "data_center",
            "sync_execution_identity",
            observation.identity.identity_hash,
            _IDENTITY_VERSION,
            observation.identity.identity_hash,
        ),
        *(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                publication.publication_id,
                publication.publication_version,
                publication.publication_hash,
            )
            for publication in publications
        ),
    )
    detail: dict[str, JSONValue] = {
        "sync_identity_id": observation.identity.identity_hash,
        "sync_identity_version": _IDENTITY_VERSION,
        "sync_identity_hash": observation.identity.identity_hash,
        "target_date": observation.target_date.isoformat(),
        "sections": section_detail,
        "remaining_blocker_count": sum(section.remaining_blocker_count for section in sections),
        "publications": publication_detail,
        "publication_count": len(publications),
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.repair.completed",
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=observation.outcome,
        severity=AuditSeverity.INFO,
        reason_codes=("repair_completed",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="decision_reliability_repair",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.identity.provider_name,
            capability="repair",
            evidence_ref=observation.identity.identity_hash,
        ),
        resource=AuditResourceRef("repair_run", observation.run_id, _EVENT_VERSION),
        dataset_key=observation.dataset_key,
        provider_key=observation.identity.provider_name,
        capability="repair",
        publication_id=None,
        evidence_refs=evidence_refs,
        detail_schema="data.repair.completed.v1",
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"data-repair:{observation.identity.identity_hash}",
        scope=observation.scope,
    )


class AppendDataRepairAuditObservationUseCase:
    """Append one scoped repair completion and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataRepairAuditEventOutboxWriter,
        scope_provider: DataRepairAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataRepairAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind authority and append one exact repair completion."""

        if not isinstance(observation, DataRepairAuditObservation):
            raise TypeError("observation must be a DataRepairAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped_observation = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped_observation)
        stream_id = _stream_id(scoped_observation)
        with self._writer.atomic():
            winner = self._writer.get_winner(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=scoped_observation.recorded_at,
            )
            if winner is not None:
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = self._writer.get_current_head(
                    stream_id=stream_id,
                    as_of=scoped_observation.recorded_at,
                    scope=scope,
                )
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
            event = build_data_repair_audit_event(
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
            raise ValueError("data repair audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataRepairAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataRepairAuditObservationUseCase",
    "build_data_repair_audit_event",
    "DataRepairAuditEventOutboxWriter",
    "DataRepairAuditObservation",
    "DataRepairAuditScopeProvider",
    "RepairPublicationEvidence",
    "RepairSectionEvidence",
]
