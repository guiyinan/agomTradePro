"""Caller-owned Audit append and exact replay verification for Risk rule retirement."""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    JSONValue,
    SystemAuditEvent,
)
from core.exceptions import BusinessLogicError

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_EVENT_VERSION = "1"
_SCHEMA_VERSION = "system-audit-event.v1"
_EVENT_TYPE = "risk.execution_rule.retired"
_DETAIL_SCHEMA = "risk.execution_rule.retired.v1"
_STREAM_PREFIX = "risk.execution-rule:"


class ExecutionRuleRetirementAuditError(BusinessLogicError):
    """Audit append or exact replay verification failed."""

    default_message = "A-share execution rule retirement Audit failed"
    default_code = "A_SHARE_RULE_RETIREMENT_AUDIT_FAILED"
    default_status_code = 503


class ExecutionRuleRetirementAuditConflict(ExecutionRuleRetirementAuditError):
    """The deterministic retirement audit identity has a different winner."""

    default_message = "A-share execution rule retirement Audit identity conflicts"
    default_code = "A_SHARE_RULE_RETIREMENT_AUDIT_CONFLICT"
    default_status_code = 409


class ExecutionRuleRetirementAuditCorruption(ExecutionRuleRetirementAuditError):
    """The persisted event/outbox pair is absent, changed, or non-exact."""

    default_message = "A-share execution rule retirement Audit state is inconsistent"
    default_code = "A_SHARE_RULE_RETIREMENT_AUDIT_CORRUPT"


class ExecutionRuleRetirementAuditUnavailable(ExecutionRuleRetirementAuditError):
    """A same-transaction Audit capability is unavailable."""

    default_message = "A-share execution rule retirement Audit is unavailable"
    default_code = "A_SHARE_RULE_RETIREMENT_AUDIT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ExecutionRuleRetirementAuditObservation:
    """Audit-safe retirement facts and server-resolved actor/scope references."""

    security_id: str
    rule_id: str
    rule_version: str
    content_hash: str
    request_id: UUID
    request_hash: str
    reason_code: str
    effective_at: datetime
    recorded_at: datetime
    actor_type: str
    actor_id: str
    scope_tenant_id: str
    scope_owner_id: str

    def __post_init__(self) -> None:
        """Validate complete retirement identity, actor, scope, times, and request hash."""

        for name, value, limit in (
            ("security_id", self.security_id, 192),
            ("rule_id", self.rule_id, 192),
            ("rule_version", self.rule_version, 192),
            ("actor_type", self.actor_type, 64),
            ("actor_id", self.actor_id, 256),
            ("scope_tenant_id", self.scope_tenant_id, 192),
            ("scope_owner_id", self.scope_owner_id, 192),
        ):
            _require_token(value, name, limit)
        if type(self.content_hash) is not str or _HASH_RE.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must be a lowercase SHA-256 digest")
        if type(self.request_hash) is not str or _HASH_RE.fullmatch(self.request_hash) is None:
            raise ValueError("request_hash must be a lowercase SHA-256 digest")
        if type(self.request_id) is not UUID:
            raise ValueError("request_id must be a UUID")
        if (
            type(self.reason_code) is not str
            or len(self.reason_code) > 128
            or _REASON_RE.fullmatch(self.reason_code) is None
        ):
            raise ValueError("reason_code must be a bounded canonical code")
        _require_aware(self.effective_at, "effective_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.effective_at < self.recorded_at:
            raise ValueError("effective_at cannot precede recorded_at")

    @property
    def event_id(self) -> str:
        """Return the globally deterministic event identity for this request."""

        return f"risk-rule-retirement-{self.request_id}"

    @property
    def idempotency_key(self) -> str:
        """Return the globally deterministic outbox identity for this request."""

        return f"risk-rule-retirement-{self.request_id}"

    @property
    def stream_id(self) -> str:
        """Return the per-security Audit stream identity."""

        return f"{_STREAM_PREFIX}{self.security_id}"


class _ExecutionRuleRetirementAuditWriter(Protocol):
    """Narrow public Audit Application capability required by retirement."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by event and outbox storage."""

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Bind event and outbox operations to the caller's outer transaction."""

    def lock_stream(self, stream_id: str) -> None:
        """Serialize one stream before reading its head."""

    def get_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one exact event identity under the caller's transaction."""

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read and lock the latest stream event visible at the cutoff."""

    def get_exact_outbox_winner_targeted(
        self, event: SystemAuditEvent
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read the exact outbox row using its canonical event identity."""

    def append_and_enqueue_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef | None = None,
        identity_winner: SystemAuditEvent | None = None,
        stream_head: SystemAuditEvent | None = None,
    ) -> SystemAuditEventOutboxCommit:
        """Append the event and outbox row in the active caller-owned transaction."""


class AppendExecutionRuleRetirementAuditUseCase:
    """Append a new retirement audit pair or verify its exact persisted replay."""

    def __init__(self, writer: _ExecutionRuleRetirementAuditWriter) -> None:
        """Require one same-alias Audit coordinator explicitly."""

        self._writer = writer

    @property
    def database_alias(self) -> str:
        """Return the Audit coordinator alias for same-transaction composition."""

        return self._writer.database_alias

    def execute_in_caller_transaction(
        self,
        observation: ExecutionRuleRetirementAuditObservation,
        *,
        exact_replay: bool,
    ) -> SystemAuditEventOutboxCommit:
        """Write the first pair or prove both event and outbox are exact on replay."""

        if type(observation) is not ExecutionRuleRetirementAuditObservation:
            raise ExecutionRuleRetirementAuditUnavailable("retirement audit observation is invalid")
        try:
            with self._writer.caller_owned_atomic():
                self._writer.lock_stream(observation.stream_id)
                winner = self._writer.get_winner_targeted(
                    event_id=observation.event_id,
                    event_version=_EVENT_VERSION,
                    as_of=observation.recorded_at,
                    lock=True,
                )
                if exact_replay:
                    return self._verify_replay(observation=observation, winner=winner)
                if winner is not None:
                    raise ExecutionRuleRetirementAuditCorruption(
                        "unretired rule already has its deterministic Audit event"
                    )
                return self._append_first(observation)
        except ExecutionRuleRetirementAuditError:
            raise
        except SystemAuditEventOutboxConflict as error:
            raise ExecutionRuleRetirementAuditConflict(
                "retirement event/outbox identity conflicts with a persisted winner"
            ) from error
        except Exception as error:
            raise ExecutionRuleRetirementAuditUnavailable(
                "same-transaction retirement Audit operation failed"
            ) from error

    def _append_first(
        self,
        observation: ExecutionRuleRetirementAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        scope = _scope(observation)
        head = self._writer.get_current_head_targeted(
            stream_id=observation.stream_id,
            as_of=observation.recorded_at,
            scope=scope,
            lock=True,
        )
        sequence_no = head.sequence_no + 1 if head is not None else 1
        predecessor_hash = head.content_hash if head is not None else None
        event = build_execution_rule_retirement_audit_event(
            observation,
            sequence_no=sequence_no,
            predecessor_hash=predecessor_hash,
        )
        orphan = self._writer.get_exact_outbox_winner_targeted(event)
        if orphan is not None:
            raise ExecutionRuleRetirementAuditCorruption(
                "outbox identity exists without its retirement event winner"
            )
        commit = self._writer.append_and_enqueue_targeted(
            event,
            expected_predecessor_hash=event.predecessor_hash,
            recorded_at=event.recorded_at,
            scope=scope,
            identity_winner=None,
            stream_head=head,
        )
        if commit.event != event:
            raise ExecutionRuleRetirementAuditCorruption(
                "Audit writer substituted the first retirement event"
            )
        return commit

    def _verify_replay(
        self,
        *,
        observation: ExecutionRuleRetirementAuditObservation,
        winner: SystemAuditEvent | None,
    ) -> SystemAuditEventOutboxCommit:
        if winner is None:
            raise ExecutionRuleRetirementAuditCorruption(
                "retired rule has no deterministic Audit event winner"
            )
        if type(winner) is not SystemAuditEvent:
            raise ExecutionRuleRetirementAuditCorruption(
                "retirement event selector returned an invalid event type"
            )
        try:
            winner.validate_hashes()
        except (TypeError, ValueError) as error:
            raise ExecutionRuleRetirementAuditCorruption(
                "persisted retirement event failed hash validation"
            ) from error
        expected = build_execution_rule_retirement_audit_event(
            observation,
            sequence_no=winner.sequence_no,
            predecessor_hash=winner.predecessor_hash,
        )
        if winner != expected:
            raise ExecutionRuleRetirementAuditCorruption(
                "persisted retirement event differs from the exact rule operation"
            )
        outbox = self._writer.get_exact_outbox_winner_targeted(expected)
        if type(outbox) is not ExactSystemAuditOutboxWinner:
            raise ExecutionRuleRetirementAuditCorruption(
                "persisted retirement event has no exact outbox winner"
            )
        try:
            ExactSystemAuditOutboxWinner.__post_init__(outbox)
        except (TypeError, ValueError) as error:
            raise ExecutionRuleRetirementAuditCorruption(
                "persisted retirement outbox winner failed integrity validation"
            ) from error
        if (
            outbox.event != expected
            or outbox.event_id != expected.event_id
            or outbox.idempotency_key != expected.idempotency_key
            or outbox.payload_hash != expected.content_hash
        ):
            raise ExecutionRuleRetirementAuditCorruption(
                "persisted retirement event has a non-exact outbox winner"
            )
        return SystemAuditEventOutboxCommit(
            event=expected,
            outbox_id=outbox.outbox_id,
            event_id=outbox.event_id,
            idempotency_key=outbox.idempotency_key,
        )


def build_execution_rule_retirement_audit_event(
    observation: ExecutionRuleRetirementAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build the exact canonical event for one source-rule retirement."""

    if type(observation) is not ExecutionRuleRetirementAuditObservation:
        raise ValueError("observation must be a typed retirement audit value")
    ExecutionRuleRetirementAuditObservation.__post_init__(observation)
    if type(sequence_no) is not int or sequence_no < 1:
        raise ValueError("sequence_no must be positive")
    scope = _scope(observation)
    detail: dict[str, JSONValue] = {
        "security_id": observation.security_id,
        "rule_id": observation.rule_id,
        "rule_version": observation.rule_version,
        "content_hash": observation.content_hash,
        "request_id": str(observation.request_id),
        "request_hash": observation.request_hash,
        "reason_code": observation.reason_code,
        "effective_at": _utc_text(observation.effective_at),
    }
    return SystemAuditEvent.create(
        event_id=observation.event_id,
        event_version=_EVENT_VERSION,
        schema_version=_SCHEMA_VERSION,
        category=AuditCategory.SYSTEM_CONFIGURATION,
        event_type=_EVENT_TYPE,
        owner="risk_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.WARNING,
        reason_codes=("execution_rule_retired",),
        occurred_at=observation.recorded_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef(
            actor_type=observation.actor_type,
            actor_id=observation.actor_id,
        ),
        source_app="risk_center",
        source_component="execution_rule_lifecycle",
        source_surface="internal",
        correlations=AuditCorrelations(request_id=str(observation.request_id)),
        resource=AuditResourceRef(
            resource_type="a_share_execution_rule",
            resource_id=observation.security_id,
            resource_version=observation.content_hash,
        ),
        dataset_key=None,
        provider_key=None,
        capability=None,
        publication_id=None,
        evidence_refs=(),
        detail_schema=_DETAIL_SCHEMA,
        detail=detail,
        stream_id=observation.stream_id,
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=observation.idempotency_key,
        scope=scope,
    )


def _scope(observation: ExecutionRuleRetirementAuditObservation) -> AuditScopeRef:
    return AuditScopeRef(
        tenant_id=observation.scope_tenant_id,
        owner_id=observation.scope_owner_id,
    )


def _require_token(value: str, field: str, maximum: int) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field} must be a bounded canonical token")


def _require_aware(value: datetime, field: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = [
    "AppendExecutionRuleRetirementAuditUseCase",
    "ExecutionRuleRetirementAuditConflict",
    "ExecutionRuleRetirementAuditCorruption",
    "ExecutionRuleRetirementAuditError",
    "ExecutionRuleRetirementAuditObservation",
    "ExecutionRuleRetirementAuditUnavailable",
    "build_execution_rule_retirement_audit_event",
]
