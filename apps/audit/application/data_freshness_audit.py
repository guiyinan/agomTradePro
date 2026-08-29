"""Canonical publication-bound freshness state transitions."""

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

_EVENT_TYPE: Final[str] = "data.freshness.changed"
_DETAIL_SCHEMA: Final[str] = "data.freshness.changed.v1"
_EVENT_VERSION: Final[str] = "1"
_HASH_LENGTH: Final[int] = 64
_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REASON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _require_identifier(value: object, field_name: str) -> str:
    """Return one bounded canonical token or raise."""

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


def _require_blocked_reason(value: object, field_name: str) -> str:
    """Return one stable non-sensitive blocker code or raise."""

    if type(value) is not str or len(value) > 128 or _REASON_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a stable reason code")
    return value


@dataclass(frozen=True, slots=True)
class DataFreshnessAuditObservation:
    """Immutable freshness state evaluated against one exact publication."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    freshness_status: str
    must_not_use_for_decision: bool
    occurred_at: datetime
    recorded_at: datetime
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
            "freshness_status",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.publication_hash, "publication_hash")
        if type(self.must_not_use_for_decision) is not bool:
            raise TypeError("must_not_use_for_decision must be a boolean")
        if self.must_not_use_for_decision:
            _require_blocked_reason(self.blocked_reason, "blocked_reason")
        elif self.blocked_reason is not None:
            raise ValueError("usable freshness observation cannot carry a blocked reason")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


def _stable_event_id(observation: DataFreshnessAuditObservation) -> str:
    """Return the deterministic identity for one exact freshness transition input."""

    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.freshness_status,
            str(observation.must_not_use_for_decision),
            observation.blocked_reason or "",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-freshness-{digest}"


def _stream_id(observation: DataFreshnessAuditObservation) -> str:
    """Return the stable dataset/publication-key freshness stream."""

    return f"data.freshness:{observation.dataset_key}:{observation.publication_key}"


def _validate_previous_state(
    *,
    freshness_status: object,
    must_not_use_for_decision: object,
    blocked_reason: object,
) -> tuple[str, bool | None, str | None]:
    """Validate one prior transition state read from the canonical stream."""

    status = _require_identifier(freshness_status, "previous_freshness_status")
    if must_not_use_for_decision is None:
        if status != "unknown" or blocked_reason is not None:
            raise ValueError("unknown previous freshness state is inconsistent")
        return status, None, None
    if type(must_not_use_for_decision) is not bool:
        raise TypeError("previous_must_not_use_for_decision must be boolean or None")
    if must_not_use_for_decision:
        reason = _require_blocked_reason(blocked_reason, "previous_blocked_reason")
        return status, True, reason
    if blocked_reason is not None:
        raise ValueError("usable previous freshness state cannot carry a blocker")
    return status, False, None


class DataFreshnessAuditScopeProvider(Protocol):
    """Resolve authoritative scope for one freshness transition."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated server-issued scope at ``as_of``."""


class DataFreshnessAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical freshness event/outbox writer with exact replay reads."""

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


def build_data_freshness_audit_event(
    observation: DataFreshnessAuditObservation,
    *,
    previous_freshness_status: str,
    previous_must_not_use_for_decision: bool | None,
    previous_blocked_reason: str | None,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one registered freshness transition with exact publication evidence."""

    if not isinstance(observation, DataFreshnessAuditObservation):
        raise TypeError("observation must be a DataFreshnessAuditObservation")
    previous_status, previous_blocked, previous_reason = _validate_previous_state(
        freshness_status=previous_freshness_status,
        must_not_use_for_decision=previous_must_not_use_for_decision,
        blocked_reason=previous_blocked_reason,
    )
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    outcome = (
        AuditOutcome.BLOCKED if observation.must_not_use_for_decision else AuditOutcome.RECOVERED
    )
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "previous_freshness_status": previous_status,
        "freshness_status": observation.freshness_status,
        "previous_must_not_use_for_decision": previous_blocked,
        "must_not_use_for_decision": observation.must_not_use_for_decision,
        "previous_blocked_reason": previous_reason,
        "blocked_reason": observation.blocked_reason,
    }
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=_EVENT_TYPE,
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=outcome,
        severity=AuditSeverity.WARNING,
        reason_codes=("freshness_changed",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication_freshness_gate",
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
        capability="freshness",
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
            f"data-freshness:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.publication_id}:{observation.freshness_status}:"
            f"{observation.must_not_use_for_decision}:{observation.blocked_reason or 'none'}"
        ),
        scope=observation.scope,
    )


def _state_from_event(event: SystemAuditEvent) -> tuple[str, bool, str | None]:
    """Read the current state from one validated canonical freshness head."""

    if event.event_type != _EVENT_TYPE or event.detail_schema != _DETAIL_SCHEMA:
        raise ValueError("freshness stream head has an unexpected contract")
    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise ValueError("freshness stream head failed integrity validation") from error
    status = _require_identifier(event.detail.get("freshness_status"), "freshness_status")
    blocked = event.detail.get("must_not_use_for_decision")
    reason = event.detail.get("blocked_reason")
    if type(blocked) is not bool:
        raise TypeError("freshness stream head has an invalid blocked state")
    if blocked:
        return status, True, _require_blocked_reason(reason, "blocked_reason")
    if reason is not None:
        raise ValueError("usable freshness stream head carries a blocker")
    return status, False, None


def _previous_state_from_winner(
    event: SystemAuditEvent,
) -> tuple[str, bool | None, str | None]:
    """Recover the exact prior state embedded in an idempotent winner."""

    if event.event_type != _EVENT_TYPE or event.detail_schema != _DETAIL_SCHEMA:
        raise ValueError("freshness winner has an unexpected contract")
    try:
        event.validate_hashes()
    except (TypeError, ValueError) as error:
        raise ValueError("freshness winner failed integrity validation") from error
    return _validate_previous_state(
        freshness_status=event.detail.get("previous_freshness_status"),
        must_not_use_for_decision=event.detail.get("previous_must_not_use_for_decision"),
        blocked_reason=event.detail.get("previous_blocked_reason"),
    )


class AppendDataFreshnessAuditObservationUseCase:
    """Append only actual freshness-state changes and their outbox records."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataFreshnessAuditEventOutboxWriter,
        scope_provider: DataFreshnessAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataFreshnessAuditObservation,
    ) -> SystemAuditEventOutboxCommit | None:
        """Bind authority, derive prior state, and append only a true transition."""

        if not isinstance(observation, DataFreshnessAuditObservation):
            raise TypeError("observation must be a DataFreshnessAuditObservation")
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
                previous_status, previous_blocked, previous_reason = _previous_state_from_winner(
                    winner
                )
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = self._writer.get_current_head(
                    stream_id=stream_id,
                    as_of=scoped.recorded_at,
                    scope=scope,
                )
                if head is None:
                    previous_status = "unknown"
                    previous_blocked = None
                    previous_reason = None
                    sequence_no = 1
                    predecessor_hash = None
                else:
                    previous_status, previous_blocked, previous_reason = _state_from_event(head)
                    current_state = (
                        scoped.freshness_status,
                        scoped.must_not_use_for_decision,
                        scoped.blocked_reason,
                    )
                    if current_state == (
                        previous_status,
                        previous_blocked,
                        previous_reason,
                    ):
                        return None
                    sequence_no = head.sequence_no + 1
                    predecessor_hash = head.content_hash
            event = build_data_freshness_audit_event(
                scoped,
                previous_freshness_status=previous_status,
                previous_must_not_use_for_decision=previous_blocked,
                previous_blocked_reason=previous_reason,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            commit = self._writer.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
        if commit.event != event:
            raise ValueError("data freshness audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataFreshnessAuditObservation,
    ) -> SystemAuditEventOutboxCommit | None:
        """Write one transition through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataFreshnessAuditObservationUseCase",
    "build_data_freshness_audit_event",
    "DataFreshnessAuditEventOutboxWriter",
    "DataFreshnessAuditObservation",
    "DataFreshnessAuditScopeProvider",
]
