"""Typed Data Center validation-rejection events for the unified audit ledger."""

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
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DataValidationRejectedObservation:
    """Immutable rejection with exact run and RawAudit evidence identity."""

    dataset_key: str
    validator_key: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    raw_audit_id: str
    raw_audit_version: str
    raw_audit_content_hash: str
    rejection_reason: str
    error_class: str
    rejected_count: int
    occurred_at: datetime
    recorded_at: datetime
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "validator_key",
            "provider_key",
            "run_id",
            "ingested_run_id",
            "raw_audit_id",
            "raw_audit_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.raw_audit_content_hash, "raw_audit_content_hash")
        if (
            not isinstance(self.rejection_reason, str)
            or len(self.rejection_reason) > 128
            or _REASON_PATTERN.fullmatch(self.rejection_reason) is None
        ):
            raise ValueError("rejection_reason must be a stable reason code")
        if (
            not isinstance(self.error_class, str)
            or _ERROR_CLASS_PATTERN.fullmatch(self.error_class) is None
        ):
            raise ValueError("error_class must contain only a class name")
        if (
            not isinstance(self.rejected_count, int)
            or isinstance(self.rejected_count, bool)
            or self.rejected_count <= 0
        ):
            raise ValueError("rejected_count must be a positive integer")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataValidationRejectedObservation) -> str:
    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.validator_key,
            observation.raw_audit_id,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-validation-{digest}"


class DataValidationAuditScopeProvider(Protocol):
    """Resolve the current authoritative scope for a validation event."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataValidationAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
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


def build_data_validation_rejected_event(
    observation: DataValidationRejectedObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical validation-rejection event."""

    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.validation.rejected",
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.BLOCKED,
        severity=AuditSeverity.ERROR,
        reason_codes=("validation_rejected", observation.rejection_reason),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="validation",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
        ),
        resource=AuditResourceRef(
            "raw_audit",
            observation.raw_audit_id,
            observation.raw_audit_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability="validation",
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
        detail_schema="data.validation.rejected.v1",
        detail={
            "validator_key": observation.validator_key,
            "rejection_reason": observation.rejection_reason,
            "error_class": observation.error_class,
            "rejected_count": observation.rejected_count,
        },
        stream_id=f"data.validation:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-validation:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.validator_key}:{observation.raw_audit_id}"
        ),
        scope=observation.scope,
    )


class AppendDataValidationRejectedObservationUseCase:
    """Append one scoped validation rejection and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataValidationAuditEventOutboxWriter,
        scope_provider: DataValidationAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataValidationRejectedObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind current authority, preserve first-winner replay, and append."""

        if not isinstance(observation, DataValidationRejectedObservation):
            raise TypeError("observation must be a DataValidationRejectedObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped_observation = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped_observation)
        stream_id = f"data.validation:{scoped_observation.dataset_key}"
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
            event = build_data_validation_rejected_event(
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
            raise ValueError("data validation audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataValidationRejectedObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataValidationRejectedObservationUseCase",
    "DataValidationAuditEventOutboxWriter",
    "DataValidationAuditScopeProvider",
    "DataValidationRejectedObservation",
    "build_data_validation_rejected_event",
]
