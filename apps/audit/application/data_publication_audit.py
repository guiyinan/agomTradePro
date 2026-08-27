"""Typed canonical-publication events for the unified audit ledger."""

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


def _require_count(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DataPublicationAuditObservation:
    """Immutable publication outcome with exact run and evidence references."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    member_count: int
    coverage_requested_count: int
    coverage_eligible_count: int
    coverage_selected_count: int
    outcome: AuditOutcome
    raw_audit_id: str
    raw_audit_version: str
    raw_audit_content_hash: str
    occurred_at: datetime
    recorded_at: datetime
    blocked_reason: str | None = None
    error_class: str | None = None
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
            "raw_audit_id",
            "raw_audit_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.publication_hash, "publication_hash")
        _require_digest(self.raw_audit_content_hash, "raw_audit_content_hash")
        for field_name in (
            "member_count",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
        ):
            _require_count(getattr(self, field_name), field_name)
        if self.coverage_selected_count > self.coverage_eligible_count:
            raise ValueError("selected coverage cannot exceed eligible coverage")
        if self.coverage_eligible_count > self.coverage_requested_count:
            raise ValueError("eligible coverage cannot exceed requested coverage")
        if self.member_count != self.coverage_selected_count:
            raise ValueError("member_count must equal selected coverage")
        if self.outcome not in {AuditOutcome.PUBLISHED, AuditOutcome.BLOCKED}:
            raise ValueError("publication outcome must be published or blocked")
        if self.outcome is AuditOutcome.PUBLISHED:
            if self.member_count == 0:
                raise ValueError("published observation requires at least one member")
            if self.blocked_reason is not None:
                raise ValueError("published observation cannot carry a blocked reason")
            if self.error_class is not None:
                raise ValueError("published observation cannot carry an error class")
        else:
            if (
                not isinstance(self.blocked_reason, str)
                or len(self.blocked_reason) > 128
                or _REASON_PATTERN.fullmatch(self.blocked_reason) is None
            ):
                raise ValueError("blocked observation requires a stable reason code")
            if self.error_class is not None:
                _require_identifier(self.error_class, "error_class")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataPublicationAuditObservation) -> str:
    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.outcome.value,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-publication-{digest}"


class DataPublicationAuditScopeProvider(Protocol):
    """Resolve the exact current scope for one publication audit write."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataPublicationAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
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


def build_data_publication_audit_event(
    observation: DataPublicationAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical published or blocked publication event."""

    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    published = observation.outcome is AuditOutcome.PUBLISHED
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "member_count": observation.member_count,
        "coverage_requested_count": observation.coverage_requested_count,
        "coverage_eligible_count": observation.coverage_eligible_count,
        "coverage_selected_count": observation.coverage_selected_count,
    }
    reason_codes: tuple[str, ...] = ("publication_published",)
    if not published:
        blocked_reason = observation.blocked_reason
        if blocked_reason is None:
            raise ValueError("blocked publication observation is missing its reason")
        detail["blocked_reason"] = blocked_reason
        if observation.error_class is not None:
            detail["error_class"] = observation.error_class
        reason_codes = ("publication_blocked", blocked_reason)
    evidence_refs = [
        AuditEvidenceRef(
            "data_center",
            "raw_audit",
            observation.raw_audit_id,
            observation.raw_audit_version,
            observation.raw_audit_content_hash,
        )
    ]
    if published:
        evidence_refs.append(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                observation.publication_id,
                observation.publication_version,
                observation.publication_hash,
            )
        )
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=("data.publication.published" if published else "data.publication.blocked"),
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=observation.outcome,
        severity=AuditSeverity.INFO if published else AuditSeverity.CRITICAL,
        reason_codes=reason_codes,
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
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
        capability="publication",
        publication_id=observation.publication_id,
        evidence_refs=tuple(evidence_refs),
        detail_schema=(
            "data.publication.published.v1" if published else "data.publication.blocked.v1"
        ),
        detail=detail,
        stream_id=f"data.publication:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-publication:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.publication_id}:{observation.outcome.value}"
        ),
        scope=observation.scope,
    )


class AppendDataPublicationAuditObservationUseCase:
    """Append one scoped publication observation and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataPublicationAuditEventOutboxWriter,
        scope_provider: DataPublicationAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind current authority, preserve first-winner replay, and append."""

        if not isinstance(observation, DataPublicationAuditObservation):
            raise TypeError("observation must be a DataPublicationAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped_observation = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped_observation)
        stream_id = f"data.publication:{scoped_observation.dataset_key}"
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
            event = build_data_publication_audit_event(
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
            raise ValueError("data publication audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataPublicationAuditObservationUseCase",
    "DataPublicationAuditEventOutboxWriter",
    "DataPublicationAuditObservation",
    "DataPublicationAuditScopeProvider",
    "build_data_publication_audit_event",
]
