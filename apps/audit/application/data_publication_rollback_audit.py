"""Canonical audit contract for explicit publication rollbacks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
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

_EVENT_VERSION: Final[str] = "1"
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


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware timestamp or raise."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DataPublicationRollbackAuditObservation:
    """Immutable rollback transition backed by three exact evidence records."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    rollback_id: str
    rollback_version: str
    rollback_content_hash: str
    previous_publication_id: str
    previous_publication_version: str
    previous_publication_hash: str
    run_id: str
    occurred_at: datetime
    recorded_at: datetime
    outcome: AuditOutcome
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_key",
            "publication_version",
            "rollback_version",
            "previous_publication_version",
            "run_id",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        for field_name in (
            "publication_id",
            "rollback_id",
            "previous_publication_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        for field_name in (
            "publication_hash",
            "rollback_content_hash",
            "previous_publication_hash",
        ):
            _require_digest(getattr(self, field_name), field_name)
        if self.publication_id == self.previous_publication_id:
            raise ValueError("rollback target and previous publication must differ")
        if self.outcome is not AuditOutcome.ROLLED_BACK:
            raise ValueError("publication rollback outcome must be rolled_back")
        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        if occurred_at > recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataPublicationRollbackAuditObservation) -> str:
    """Return the deterministic identity for one durable rollback row."""

    material = "|".join(
        (
            observation.rollback_id,
            observation.publication_id,
            observation.publication_hash,
            observation.rollback_content_hash,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-publication-rollback-{digest}"


def _stream_id(observation: DataPublicationRollbackAuditObservation) -> str:
    """Return the existing canonical publication lifecycle stream."""

    return f"data.publication:{observation.dataset_key}"


class DataPublicationRollbackAuditScopeProvider(Protocol):
    """Resolve authoritative scope for one publication rollback."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated server-issued scope at ``as_of``."""


class DataPublicationRollbackAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical rollback event/outbox writer with exact replay reads."""

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


def build_data_publication_rollback_audit_event(
    observation: DataPublicationRollbackAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one required rollback event without exposing operator text."""

    if not isinstance(observation, DataPublicationRollbackAuditObservation):
        raise TypeError("observation must be a DataPublicationRollbackAuditObservation")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "rollback_id": observation.rollback_id,
        "rollback_content_hash": observation.rollback_content_hash,
        "previous_publication_id": observation.previous_publication_id,
        "previous_publication_version": observation.previous_publication_version,
        "previous_publication_hash": observation.previous_publication_hash,
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.publication.rolled_back",
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=AuditOutcome.ROLLED_BACK,
        severity=AuditSeverity.WARNING,
        reason_codes=("publication_rolled_back",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=observation.occurred_at,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication_rollback",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            dataset_key=observation.dataset_key,
            capability="publication",
            publication_id=observation.publication_id,
            evidence_ref=observation.rollback_id,
        ),
        resource=AuditResourceRef(
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=None,
        capability="publication",
        publication_id=observation.publication_id,
        evidence_refs=(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                observation.publication_id,
                observation.publication_version,
                observation.publication_hash,
            ),
            AuditEvidenceRef(
                "data_center",
                "publication_rollback",
                observation.rollback_id,
                observation.rollback_version,
                observation.rollback_content_hash,
            ),
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                observation.previous_publication_id,
                observation.previous_publication_version,
                observation.previous_publication_hash,
            ),
        ),
        detail_schema="data.publication.rolled_back.v1",
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=f"data-publication-rollback:{observation.rollback_id}",
        scope=observation.scope,
    )


class AppendDataPublicationRollbackAuditObservationUseCase:
    """Append one scoped rollback event and its canonical outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataPublicationRollbackAuditEventOutboxWriter,
        scope_provider: DataPublicationRollbackAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataPublicationRollbackAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind authority and append or replay one exact rollback event."""

        if not isinstance(observation, DataPublicationRollbackAuditObservation):
            raise TypeError("observation must be a DataPublicationRollbackAuditObservation")
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
            event = build_data_publication_rollback_audit_event(
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
            raise ValueError("publication rollback audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataPublicationRollbackAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataPublicationRollbackAuditObservationUseCase",
    "build_data_publication_rollback_audit_event",
    "DataPublicationRollbackAuditEventOutboxWriter",
    "DataPublicationRollbackAuditObservation",
    "DataPublicationRollbackAuditScopeProvider",
]
