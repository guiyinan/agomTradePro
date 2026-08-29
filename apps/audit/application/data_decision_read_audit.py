"""Typed decision-read outcomes for the unified audit ledger."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol

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

_EVENT_VERSION: Final[str] = "1"
_HASH_LENGTH: Final[int] = 64
_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REASON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _require_identifier(value: str, field_name: str) -> None:
    """Require one bounded canonical identifier."""

    if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a bounded canonical identifier")


def _require_digest(value: str, field_name: str) -> None:
    """Require one lowercase SHA-256 digest."""

    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require one timezone-aware instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DataDecisionReadAuditObservation:
    """Immutable publication-bound decision-read outcome."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    decision_key: str
    freshness_status: str
    outcome: AuditOutcome
    recorded_at: datetime
    occurred_at: datetime
    blocked_reason: str | None = None
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_version",
            "provider_key",
            "run_id",
            "ingested_run_id",
            "decision_key",
            "freshness_status",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.publication_hash, "publication_hash")
        if self.outcome not in {AuditOutcome.RECOVERED, AuditOutcome.BLOCKED}:
            raise ValueError("decision-read outcome must be recovered or blocked")
        if self.outcome is AuditOutcome.RECOVERED:
            if self.blocked_reason is not None:
                raise ValueError("recovered decision read cannot carry a blocked reason")
        elif (
            not isinstance(self.blocked_reason, str)
            or len(self.blocked_reason) > 128
            or _REASON_PATTERN.fullmatch(self.blocked_reason) is None
        ):
            raise ValueError("blocked decision read requires a stable reason code")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataDecisionReadAuditObservation) -> str:
    """Return a deterministic identity for one observable read state."""

    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.decision_key,
            observation.freshness_status,
            observation.outcome.value,
            observation.blocked_reason or "",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-decision-read-{digest}"


def _stream_id(observation: DataDecisionReadAuditObservation) -> str:
    """Return the stable decision-read stream identity."""

    return (
        f"data.decision_read:{observation.dataset_key}:"
        f"{observation.publication_key}:{observation.decision_key}"
    )


class DataDecisionReadAuditScopeProvider(Protocol):
    """Resolve the authoritative scope for one decision-read event."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataDecisionReadAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical event/outbox writer with exact replay reads."""

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


def build_data_decision_read_audit_event(
    observation: DataDecisionReadAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical recovered or blocked decision-read event."""

    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    recovered = observation.outcome is AuditOutcome.RECOVERED
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "decision_key": observation.decision_key,
        "freshness_status": observation.freshness_status,
    }
    reason_codes: tuple[str, ...] = ("decision_read_recovered",)
    if not recovered:
        blocked_reason = observation.blocked_reason
        if blocked_reason is None:
            raise ValueError("blocked decision read is missing its reason")
        detail["blocked_reason"] = blocked_reason
        reason_codes = ("decision_read_blocked", blocked_reason)
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=("data.decision_read.recovered" if recovered else "data.decision_read.blocked"),
        owner="data_center",
        write_policy=(
            AuditWritePolicy.TRANSACTIONAL_OUTBOX if recovered else AuditWritePolicy.REQUIRED
        ),
        outcome=observation.outcome,
        severity=AuditSeverity.INFO if recovered else AuditSeverity.CRITICAL,
        reason_codes=reason_codes,
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="decision_read",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            publication_id=observation.publication_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
        ),
        resource=AuditResourceRef(
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability="decision_read",
        publication_id=observation.publication_id,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                observation.publication_id,
                observation.publication_version,
                observation.publication_hash,
            ),
        ),
        detail_schema=(
            "data.decision_read.recovered.v1" if recovered else "data.decision_read.blocked.v1"
        ),
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-decision-read:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.publication_id}:{observation.decision_key}:"
            f"{observation.freshness_status}:{observation.outcome.value}:"
            f"{observation.blocked_reason or 'none'}"
        ),
        scope=observation.scope,
    )


class AppendDataDecisionReadAuditObservationUseCase:
    """Append one scoped decision-read observation and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataDecisionReadAuditEventOutboxWriter,
        scope_provider: DataDecisionReadAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataDecisionReadAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind authority, preserve exact replay, and append one read state."""

        if not isinstance(observation, DataDecisionReadAuditObservation):
            raise TypeError("observation must be a DataDecisionReadAuditObservation")
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
            event = build_data_decision_read_audit_event(
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
            raise ValueError("data decision-read audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataDecisionReadAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataDecisionReadAuditObservationUseCase",
    "DataDecisionReadAuditEventOutboxWriter",
    "DataDecisionReadAuditObservation",
    "DataDecisionReadAuditScopeProvider",
    "build_data_decision_read_audit_event",
]
