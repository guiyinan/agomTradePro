"""Canonical reconciliation-backed Data Center conflict transitions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal, Protocol
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

DataConflictTransition = Literal["detected", "resolved"]

_EVENT_VERSION: Final[str] = "1"
_EVIDENCE_VERSION: Final[str] = "1"
_HASH_LENGTH: Final[int] = 64
_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


def _require_identifier(value: object, field_name: str) -> str:
    """Return one bounded canonical identifier or raise."""

    if type(value) is not str or _TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a bounded canonical identifier")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Return one lowercase SHA-256 digest or raise."""

    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _require_uuid(value: object, field_name: str) -> str:
    """Return canonical lowercase UUID text or raise."""

    if type(value) is not str:
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a canonical UUID") from error
    if str(parsed) != value:
        raise ValueError(f"{field_name} must use canonical lowercase UUID text")
    return value


def _require_count(value: object, field_name: str) -> int:
    """Return one non-negative conflict count or raise."""

    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware timestamp or raise."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DataConflictAuditObservation:
    """Immutable semantic-conflict transition backed by exact evidence."""

    dataset_key: str
    transition: DataConflictTransition
    evidence_id: str
    evidence_version: str
    evidence_content_hash: str
    conflict_count: int
    occurred_at: datetime
    recorded_at: datetime
    previous_conflict_count: int | None = None
    previous_evidence_id: str | None = None
    previous_evidence_version: str | None = None
    previous_evidence_content_hash: str | None = None
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.dataset_key, "dataset_key")
        if self.transition not in {"detected", "resolved"}:
            raise ValueError("transition must be detected or resolved")
        _require_uuid(self.evidence_id, "evidence_id")
        _require_identifier(self.evidence_version, "evidence_version")
        _require_digest(self.evidence_content_hash, "evidence_content_hash")
        current_count = _require_count(self.conflict_count, "conflict_count")
        previous_count = self.previous_conflict_count
        if previous_count is not None:
            previous_count = _require_count(previous_count, "previous_conflict_count")

        previous_fields = (
            self.previous_evidence_id,
            self.previous_evidence_version,
            self.previous_evidence_content_hash,
        )
        has_previous_evidence = any(value is not None for value in previous_fields)
        if has_previous_evidence and not all(value is not None for value in previous_fields):
            raise ValueError("previous evidence reference must be complete")
        if previous_count is None and has_previous_evidence:
            raise ValueError("previous evidence requires previous_conflict_count")
        if previous_count is not None and not has_previous_evidence:
            raise ValueError("previous_conflict_count requires previous evidence")
        if has_previous_evidence:
            previous_id = _require_uuid(self.previous_evidence_id, "previous_evidence_id")
            _require_identifier(self.previous_evidence_version, "previous_evidence_version")
            _require_digest(
                self.previous_evidence_content_hash,
                "previous_evidence_content_hash",
            )
            if previous_id == self.evidence_id:
                raise ValueError("current and previous evidence identities must differ")

        if self.transition == "detected":
            if current_count < 1:
                raise ValueError("detected transition requires semantic conflicts")
            if previous_count not in {None, 0}:
                raise ValueError("detected transition requires a previously clean state")
        else:
            if current_count != 0:
                raise ValueError("resolved transition requires zero semantic conflicts")
            if previous_count is None or previous_count < 1:
                raise ValueError("resolved transition requires a previous conflict state")

        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        if occurred_at > recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataConflictAuditObservation) -> str:
    """Return the deterministic identity for one exact transition evidence."""

    material = "|".join(
        (
            observation.dataset_key,
            observation.transition,
            observation.evidence_id,
            observation.evidence_version,
            observation.evidence_content_hash,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-conflict-{digest}"


def _stream_id(observation: DataConflictAuditObservation) -> str:
    """Return the stable dataset conflict stream."""

    return f"data.conflict:{observation.dataset_key}"


class DataConflictAuditScopeProvider(Protocol):
    """Resolve authoritative scope for one conflict transition."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated server-issued scope at ``as_of``."""


class DataConflictAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical conflict event/outbox writer with exact replay reads."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by event and outbox writes."""

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


def build_data_conflict_audit_event(
    observation: DataConflictAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one registered conflict transition with exact evidence refs."""

    if not isinstance(observation, DataConflictAuditObservation):
        raise TypeError("observation must be a DataConflictAuditObservation")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")

    detected = observation.transition == "detected"
    event_type = "data.conflict.detected" if detected else "data.conflict.resolved"
    detail_schema = f"{event_type}.v1"
    evidence_refs: list[AuditEvidenceRef] = [
        AuditEvidenceRef(
            "data_center",
            "reconciliation_evidence",
            observation.evidence_id,
            observation.evidence_version,
            observation.evidence_content_hash,
        )
    ]
    if observation.previous_evidence_id is not None:
        evidence_refs.append(
            AuditEvidenceRef(
                "data_center",
                "reconciliation_evidence",
                observation.previous_evidence_id,
                observation.previous_evidence_version or "",
                observation.previous_evidence_content_hash or "",
            )
        )
    detail: dict[str, JSONValue] = {
        "transition": observation.transition,
        "conflict_count": observation.conflict_count,
        "previous_conflict_count": observation.previous_conflict_count,
        "evidence_id": observation.evidence_id,
        "evidence_version": observation.evidence_version,
        "evidence_content_hash": observation.evidence_content_hash,
        "previous_evidence_id": observation.previous_evidence_id,
        "previous_evidence_version": observation.previous_evidence_version,
        "previous_evidence_content_hash": observation.previous_evidence_content_hash,
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=event_type,
        owner="data_center",
        write_policy=(
            AuditWritePolicy.TRANSACTIONAL_OUTBOX if detected else AuditWritePolicy.REQUIRED
        ),
        outcome=AuditOutcome.DETECTED if detected else AuditOutcome.RECOVERED,
        severity=AuditSeverity.ERROR if detected else AuditSeverity.INFO,
        reason_codes=("conflict_detected" if detected else "conflict_resolved",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=observation.occurred_at,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="shadow_reconciliation",
        source_surface="application",
        correlations=AuditCorrelations(
            dataset_key=observation.dataset_key,
            capability="reconciliation",
            evidence_ref=observation.evidence_id,
        ),
        resource=AuditResourceRef(
            "reconciliation_evidence",
            observation.evidence_id,
            observation.evidence_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=None,
        capability="reconciliation",
        publication_id=None,
        evidence_refs=tuple(evidence_refs),
        detail_schema=detail_schema,
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-conflict:{observation.transition}:{observation.evidence_id}:"
            f"{observation.evidence_content_hash}"
        ),
        scope=observation.scope,
    )


class AppendDataConflictAuditObservationUseCase:
    """Append one scoped conflict transition and its canonical outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataConflictAuditEventOutboxWriter,
        scope_provider: DataConflictAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataConflictAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind authority and append one exact conflict transition."""

        if not isinstance(observation, DataConflictAuditObservation):
            raise TypeError("observation must be a DataConflictAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped)
        with self._writer.atomic():
            winner = self._writer.get_winner(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=scoped.recorded_at,
            )
            if winner is not None:
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = self._writer.get_current_head(
                    stream_id=_stream_id(scoped),
                    as_of=scoped.recorded_at,
                    scope=scope,
                )
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
            event = build_data_conflict_audit_event(
                scoped,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            commit = self._writer.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
        if commit.event != event:
            raise ValueError("data conflict audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataConflictAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataConflictAuditObservationUseCase",
    "build_data_conflict_audit_event",
    "DataConflictAuditEventOutboxWriter",
    "DataConflictAuditObservation",
    "DataConflictAuditScopeProvider",
    "DataConflictTransition",
]
