"""Typed provider-failover events for the unified audit ledger."""

from __future__ import annotations

import hashlib
import math
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
_ERROR_CLASS_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{field_name} must be a bounded non-empty string")


def _require_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DataFailoverAuditObservation:
    """Immutable provider switch decision with exact RawAudit evidence."""

    dataset_key: str
    capability: str
    from_provider: str
    to_provider: str
    run_id: str
    ingested_run_id: str
    raw_audit_id: str
    raw_audit_version: str
    raw_audit_content_hash: str
    tolerance: float
    observed_deviation: float | None
    reason_code: str
    outcome: AuditOutcome
    occurred_at: datetime
    recorded_at: datetime
    error_class: str | None = None
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "capability",
            "from_provider",
            "to_provider",
            "run_id",
            "ingested_run_id",
            "raw_audit_id",
            "raw_audit_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        if self.from_provider == self.to_provider:
            raise ValueError("failover providers must differ")
        _require_digest(self.raw_audit_content_hash, "raw_audit_content_hash")
        if (
            isinstance(self.tolerance, bool)
            or not isinstance(self.tolerance, (int, float))
            or not math.isfinite(float(self.tolerance))
            or not 0.0 <= float(self.tolerance) <= 1.0
        ):
            raise ValueError("tolerance must be finite and between 0 and 1")
        if self.observed_deviation is not None and (
            isinstance(self.observed_deviation, bool)
            or not isinstance(self.observed_deviation, (int, float))
            or not math.isfinite(float(self.observed_deviation))
            or float(self.observed_deviation) < 0.0
        ):
            raise ValueError("observed_deviation must be a finite non-negative ratio or None")
        if (
            not isinstance(self.reason_code, str)
            or len(self.reason_code) > 128
            or _REASON_PATTERN.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a stable reason code")
        if self.outcome not in {
            AuditOutcome.STARTED,
            AuditOutcome.SUCCESS,
            AuditOutcome.BLOCKED,
        }:
            raise ValueError("failover outcome must be started, success or blocked")
        if self.outcome is AuditOutcome.BLOCKED:
            if (
                not isinstance(self.error_class, str)
                or _ERROR_CLASS_PATTERN.fullmatch(self.error_class) is None
            ):
                raise ValueError("blocked failover requires an error class token")
        elif self.outcome is AuditOutcome.SUCCESS:
            if self.error_class is not None:
                raise ValueError("successful failover cannot include an error class")
            if self.observed_deviation is None:
                raise ValueError("successful failover requires observed consistency deviation")
            if float(self.observed_deviation) > float(self.tolerance):
                raise ValueError("successful failover deviation cannot exceed tolerance")
        else:
            if self.error_class is not None:
                raise ValueError("started failover cannot include an error class")
            if self.observed_deviation is not None:
                raise ValueError("started failover cannot include an observed deviation")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataFailoverAuditObservation) -> str:
    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.from_provider,
            observation.to_provider,
            observation.raw_audit_id,
            observation.outcome.value,
            observation.reason_code,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-failover-{digest}"


class DataFailoverAuditScopeProvider(Protocol):
    """Resolve authoritative scope for one failover event."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated server-issued scope at ``as_of``."""


class DataFailoverAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical failover event/outbox writer with exact replay reads."""

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


def build_data_failover_audit_event(
    observation: DataFailoverAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one registered start, success, rejection, or exhaustion event."""

    if not isinstance(observation, DataFailoverAuditObservation):
        raise TypeError("observation must be a DataFailoverAuditObservation")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    if observation.outcome is AuditOutcome.STARTED:
        event_type = "data.failover.started"
        detail_schema = "data.failover.started.v1"
        write_policy = AuditWritePolicy.TRANSACTIONAL_OUTBOX
        severity = AuditSeverity.WARNING
        reason_code = "failover_started"
    elif observation.outcome is AuditOutcome.SUCCESS:
        event_type = "data.failover.succeeded"
        detail_schema = "data.failover.succeeded.v1"
        write_policy = AuditWritePolicy.TRANSACTIONAL_OUTBOX
        severity = AuditSeverity.INFO
        reason_code = "failover_succeeded"
    elif observation.observed_deviation is None:
        event_type = "data.failover.exhausted"
        detail_schema = "data.failover.exhausted.v1"
        write_policy = AuditWritePolicy.REQUIRED
        severity = AuditSeverity.CRITICAL
        reason_code = "failover_exhausted"
    else:
        event_type = "data.failover.rejected"
        detail_schema = "data.failover.rejected.v1"
        write_policy = AuditWritePolicy.TRANSACTIONAL_OUTBOX
        severity = AuditSeverity.ERROR
        reason_code = "failover_rejected"
    detail: dict[str, JSONValue] = {
        "from_provider": observation.from_provider,
        "to_provider": observation.to_provider,
        "tolerance": float(observation.tolerance),
        "observed_deviation": (
            float(observation.observed_deviation)
            if observation.observed_deviation is not None
            else None
        ),
        "reason_code": observation.reason_code,
    }
    if observation.error_class is not None:
        detail["error_class"] = observation.error_class
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
        reason_codes=(reason_code,),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="provider_failover",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.to_provider,
        ),
        resource=AuditResourceRef(
            "raw_audit",
            observation.raw_audit_id,
            observation.raw_audit_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.to_provider,
        capability=observation.capability,
        publication_id=None,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "raw_audit",
                observation.raw_audit_id,
                observation.raw_audit_version,
                observation.raw_audit_content_hash,
            ),
        ),
        detail_schema=detail_schema,
        detail=detail,
        stream_id=f"data.failover:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-failover:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.from_provider}:{observation.to_provider}:"
            f"{observation.raw_audit_id}:{observation.outcome.value}"
        ),
        scope=observation.scope,
    )


class AppendDataFailoverAuditObservationUseCase:
    """Append one scoped failover event and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataFailoverAuditEventOutboxWriter,
        scope_provider: DataFailoverAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataFailoverAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind current authority, preserve first-winner replay, and append."""

        if not isinstance(observation, DataFailoverAuditObservation):
            raise TypeError("observation must be a DataFailoverAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped_observation = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped_observation)
        stream_id = f"data.failover:{scoped_observation.dataset_key}"
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
            event = build_data_failover_audit_event(
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
            raise ValueError("data failover audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataFailoverAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataFailoverAuditObservationUseCase",
    "DataFailoverAuditEventOutboxWriter",
    "DataFailoverAuditObservation",
    "DataFailoverAuditScopeProvider",
    "build_data_failover_audit_event",
]
