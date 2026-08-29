"""Canonical publication-bound Data Center quality transitions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal, Protocol, cast

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

DataQualityState = Literal["accepted", "degraded"]

_DETAIL_SCHEMA: Final[str] = "data.quality.changed.v1"
_EVENT_TYPE: Final[str] = "data.quality.changed"
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


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware timestamp or raise."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_quality_state(value: object, field_name: str) -> DataQualityState:
    """Return one canonical aggregate quality state or raise."""

    if type(value) is not str or value not in {"accepted", "degraded"}:
        raise ValueError(f"{field_name} must be accepted or degraded")
    return cast(DataQualityState, value)


@dataclass(frozen=True, slots=True)
class DataQualityStatusCount:
    """Count members in one normalized aggregate-quality bucket."""

    status: DataQualityState
    count: int

    def __post_init__(self) -> None:
        _require_quality_state(self.status, "status")
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count < 1:
            raise ValueError("count must be a positive integer")


@dataclass(frozen=True, slots=True)
class DataQualityAuditObservation:
    """Immutable aggregate quality for one exact canonical publication snapshot."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    quality_state: DataQualityState
    member_count: int
    quality_status_counts: tuple[DataQualityStatusCount, ...]
    occurred_at: datetime
    recorded_at: datetime
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
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.publication_hash, "publication_hash")
        quality_state = _require_quality_state(self.quality_state, "quality_state")
        if (
            not isinstance(self.member_count, int)
            or isinstance(self.member_count, bool)
            or self.member_count < 1
        ):
            raise ValueError("member_count must be a positive integer")
        if type(self.quality_status_counts) is not tuple:
            raise TypeError("quality_status_counts must be a tuple")
        if any(
            not isinstance(status_count, DataQualityStatusCount)
            for status_count in self.quality_status_counts
        ):
            raise TypeError("quality_status_counts contains an invalid value")
        if not self.quality_status_counts:
            raise ValueError("quality_status_counts cannot be empty")
        statuses = tuple(item.status for item in self.quality_status_counts)
        if len(set(statuses)) != len(statuses):
            raise ValueError("quality_status_counts must contain unique statuses")
        if statuses != tuple(sorted(statuses)):
            raise ValueError("quality_status_counts must use canonical status order")
        if sum(item.count for item in self.quality_status_counts) != self.member_count:
            raise ValueError("quality_status_counts must account for every member")
        projected_state: DataQualityState = (
            "degraded"
            if any(item.status == "degraded" for item in self.quality_status_counts)
            else "accepted"
        )
        if projected_state != quality_state:
            raise ValueError("quality_state differs from quality_status_counts")
        occurred_at = _require_aware(self.occurred_at, "occurred_at")
        recorded_at = _require_aware(self.recorded_at, "recorded_at")
        if occurred_at > recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataQualityAuditObservation) -> str:
    """Return deterministic identity for one exact quality observation."""

    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.publication_hash,
            observation.quality_state,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-quality-{digest}"


def _stream_id(observation: DataQualityAuditObservation) -> str:
    """Return the stable dataset/publication-key quality stream."""

    return f"data.quality:{observation.dataset_key}:{observation.publication_key}"


class DataQualityAuditScopeProvider(Protocol):
    """Resolve authoritative scope for one quality transition."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated server-issued scope at ``as_of``."""


class DataQualityAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical quality event/outbox writer with exact replay reads."""

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
        """Return the scoped stream head used for transition CAS."""


def build_data_quality_audit_event(
    observation: DataQualityAuditObservation,
    *,
    previous_quality_state: DataQualityState | None,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent | None:
    """Build one registered transition, suppressing healthy baselines and no-ops."""

    if not isinstance(observation, DataQualityAuditObservation):
        raise TypeError("observation must be a DataQualityAuditObservation")
    previous_state = (
        None
        if previous_quality_state is None
        else _require_quality_state(previous_quality_state, "previous_quality_state")
    )
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    if previous_state == observation.quality_state:
        return None
    if previous_state is None and observation.quality_state == "accepted":
        return None

    detected = observation.quality_state == "degraded"
    if not detected and previous_state != "degraded":
        raise ValueError("quality recovery requires a previous degraded state")
    status_counts: list[JSONValue] = [
        {"status": item.status, "count": item.count} for item in observation.quality_status_counts
    ]
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "previous_quality_state": previous_state,
        "quality_state": observation.quality_state,
        "member_count": observation.member_count,
        "quality_status_counts": status_counts,
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=_EVENT_TYPE,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.DETECTED if detected else AuditOutcome.RECOVERED,
        severity=AuditSeverity.WARNING,
        reason_codes=("quality_changed",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=observation.occurred_at,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication_quality_projection",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
            capability="quality",
            publication_id=observation.publication_id,
            evidence_ref=observation.publication_id,
        ),
        resource=AuditResourceRef(
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability="quality",
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
        detail_schema=_DETAIL_SCHEMA,
        detail=detail,
        stream_id=_stream_id(observation),
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-quality:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.publication_id}:{observation.quality_state}"
        ),
        scope=observation.scope,
    )


def _state_from_event(event: SystemAuditEvent) -> DataQualityState:
    """Read the normalized quality state from a validated stream head."""

    if event.event_type != _EVENT_TYPE or event.detail_schema != _DETAIL_SCHEMA:
        raise ValueError("quality stream head has an unexpected contract")
    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise ValueError("quality stream head failed integrity validation") from error
    state = _require_quality_state(event.detail.get("quality_state"), "quality_state")
    expected_outcome = AuditOutcome.DETECTED if state == "degraded" else AuditOutcome.RECOVERED
    if event.outcome is not expected_outcome:
        raise ValueError("quality stream head outcome differs from its state")
    return state


def _previous_state_from_winner(event: SystemAuditEvent) -> DataQualityState | None:
    """Recover the exact prior state embedded in an idempotent winner."""

    if event.event_type != _EVENT_TYPE or event.detail_schema != _DETAIL_SCHEMA:
        raise ValueError("quality winner has an unexpected contract")
    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise ValueError("quality winner failed integrity validation") from error
    previous = event.detail.get("previous_quality_state")
    if previous is None:
        return None
    return _require_quality_state(previous, "previous_quality_state")


class AppendDataQualityAuditObservationUseCase:
    """Append only actual publication-quality changes and their outbox records."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataQualityAuditEventOutboxWriter,
        scope_provider: DataQualityAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataQualityAuditObservation,
    ) -> SystemAuditEventOutboxCommit | None:
        """Bind authority, derive the prior state, and append only a transition."""

        if not isinstance(observation, DataQualityAuditObservation):
            raise TypeError("observation must be a DataQualityAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped = replace(observation, scope=scope)
        event_id = _stable_event_id(scoped)
        stream_id = _stream_id(scoped)
        with self._writer.atomic():
            winner = self._writer.get_winner(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=scoped.recorded_at,
            )
            if winner is not None:
                previous_state = _previous_state_from_winner(winner)
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = self._writer.get_current_head(
                    stream_id=stream_id,
                    as_of=scoped.recorded_at,
                    scope=scope,
                )
                if head is None:
                    previous_state = None
                    sequence_no = 1
                    predecessor_hash = None
                else:
                    previous_state = _state_from_event(head)
                    if previous_state == scoped.quality_state:
                        return None
                    sequence_no = head.sequence_no + 1
                    predecessor_hash = head.content_hash
            event = build_data_quality_audit_event(
                scoped,
                previous_quality_state=previous_state,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            if event is None:
                return None
            commit = self._writer.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
        if commit.event != event:
            raise ValueError("data quality audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataQualityAuditObservation,
    ) -> SystemAuditEventOutboxCommit | None:
        """Write one transition through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataQualityAuditObservationUseCase",
    "build_data_quality_audit_event",
    "DataQualityAuditEventOutboxWriter",
    "DataQualityAuditObservation",
    "DataQualityAuditScopeProvider",
    "DataQualityState",
    "DataQualityStatusCount",
]
