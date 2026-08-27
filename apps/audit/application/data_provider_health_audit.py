"""Typed provider circuit-transition outcomes for the unified audit ledger."""

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
_REASON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_TRANSITIONS: Final[dict[str, tuple[str, AuditOutcome, AuditWritePolicy, AuditSeverity, str]]] = {
    "circuit_opened": (
        "data.provider.circuit_opened",
        AuditOutcome.BLOCKED,
        AuditWritePolicy.REQUIRED,
        AuditSeverity.CRITICAL,
        "provider_circuit_opened",
    ),
    "recovered": (
        "data.provider.recovered",
        AuditOutcome.RECOVERED,
        AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        AuditSeverity.INFO,
        "provider_recovered",
    ),
}


def _require_text(value: object, field_name: str) -> str:
    """Return one bounded non-blank string without normalizing its identity."""

    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(f"{field_name} must be a bounded non-empty string")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Return one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DataProviderHealthAuditObservation:
    """Immutable circuit-open or provider-recovery transition evidence."""

    provider_key: str
    capability: str
    dataset_key: str
    run_id: str
    ingested_run_id: str
    provider_health_snapshot_id: str
    provider_health_snapshot_version: str
    provider_health_snapshot_hash: str
    transition: str
    reason_code: str
    outcome: AuditOutcome
    occurred_at: datetime
    recorded_at: datetime
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "provider_key",
            "capability",
            "dataset_key",
            "run_id",
            "ingested_run_id",
            "provider_health_snapshot_id",
            "provider_health_snapshot_version",
            "transition",
            "reason_code",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_digest(
            self.provider_health_snapshot_hash,
            "provider_health_snapshot_hash",
        )
        contract = _TRANSITIONS.get(self.transition)
        if contract is None:
            raise ValueError("provider health transition is not registered")
        if self.outcome is not contract[1]:
            raise ValueError("provider health outcome differs from its transition")
        if self.reason_code != contract[4] or _REASON_PATTERN.fullmatch(self.reason_code) is None:
            raise ValueError("provider health transition requires its stable reason code")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataProviderHealthAuditObservation) -> str:
    """Return one deterministic transition identity."""

    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.provider_key,
            observation.capability,
            observation.transition,
            observation.provider_health_snapshot_hash,
        )
    )
    return f"data-provider-health-{hashlib.sha256(material.encode('utf-8')).hexdigest()[:48]}"


def _stream_id(observation: DataProviderHealthAuditObservation) -> str:
    """Return the stable provider-capability stream identity."""

    return f"data.provider:{observation.provider_key}:{observation.capability}"


class DataProviderHealthAuditScopeProvider(Protocol):
    """Resolve the authoritative scope for one provider transition."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataProviderHealthAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical provider-transition event/outbox writer with exact replay."""

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


def build_data_provider_health_audit_event(
    observation: DataProviderHealthAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical provider circuit transition event."""

    if not isinstance(observation, DataProviderHealthAuditObservation):
        raise TypeError("observation must be a DataProviderHealthAuditObservation")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    event_type, _outcome, write_policy, severity, _reason = _TRANSITIONS[observation.transition]
    detail: dict[str, JSONValue] = {
        "transition": observation.transition,
        "provider_health_snapshot_hash": observation.provider_health_snapshot_hash,
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=event_type,
        owner="data_center",
        write_policy=write_policy,
        outcome=observation.outcome,
        severity=severity,
        reason_codes=(observation.reason_code,),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="provider_health",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
            capability=observation.capability,
            evidence_ref=observation.provider_health_snapshot_id,
        ),
        resource=AuditResourceRef(
            "provider_capability",
            f"{observation.provider_key}:{observation.capability}",
            observation.provider_health_snapshot_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability=observation.capability,
        publication_id=None,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "provider_health_snapshot",
                observation.provider_health_snapshot_id,
                observation.provider_health_snapshot_version,
                observation.provider_health_snapshot_hash,
            ),
        ),
        detail_schema=f"{event_type}.v1",
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-provider-health:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.provider_health_snapshot_hash}:{observation.transition}"
        ),
        scope=observation.scope,
    )


class AppendDataProviderHealthAuditObservationUseCase:
    """Append one scoped provider transition and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataProviderHealthAuditEventOutboxWriter,
        scope_provider: DataProviderHealthAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataProviderHealthAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind authority and append one exact provider transition."""

        if not isinstance(observation, DataProviderHealthAuditObservation):
            raise TypeError("observation must be a DataProviderHealthAuditObservation")
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
            event = build_data_provider_health_audit_event(
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
            raise ValueError("data provider-health audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataProviderHealthAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataProviderHealthAuditObservationUseCase",
    "build_data_provider_health_audit_event",
    "DataProviderHealthAuditEventOutboxWriter",
    "DataProviderHealthAuditObservation",
    "DataProviderHealthAuditScopeProvider",
]
