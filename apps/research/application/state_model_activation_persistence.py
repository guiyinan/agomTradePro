"""ID-only exact PIT and audit facades for persisted R6 activation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationAuthorizationRef,
    R6ActivationEvent,
    R6ActivationScopeRef,
)


def _require_hash(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 hash")


def _require_aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


@dataclass(frozen=True)
class R6ActivationEventRef:
    """Exact persisted event identity and live content seal."""

    event_id: str
    event_version: str
    event_hash: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.event_id, str)
            or not self.event_id
            or len(self.event_id) > 192
            or any(character.isspace() for character in self.event_id)
            or not isinstance(self.event_version, str)
            or not self.event_version
            or len(self.event_version) > 192
            or any(character.isspace() for character in self.event_version)
        ):
            raise ValueError("R6 activation event reference identity is invalid")
        _require_hash(self.event_hash, "R6 activation event reference hash")


@dataclass(frozen=True)
class GetExactR6ActivationAuthorizationCommand:
    """Exact authorization PIT query without caller-supplied evidence."""

    authorization_ref: R6ActivationAuthorizationRef
    expected_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        self.authorization_ref.__post_init__()
        _require_hash(self.expected_hash, "R6 activation authorization expected hash")
        _require_aware(self.as_of, "R6 activation authorization query as_of")


@dataclass(frozen=True)
class GetExactR6ActivationEventCommand:
    """Exact event PIT query without caller-supplied evidence."""

    event_ref: R6ActivationEventRef
    as_of: datetime

    def __post_init__(self) -> None:
        self.event_ref.__post_init__()
        _require_aware(self.as_of, "R6 activation event query as_of")


@dataclass(frozen=True)
class AuditR6ActivationEventsCommand:
    """Bounded and cursor-stable activation audit query."""

    as_of: datetime
    cursor: str | None = None
    limit: int = 100

    def __post_init__(self) -> None:
        _require_aware(self.as_of, "R6 activation audit as_of")
        if type(self.limit) is not int or not 1 <= self.limit <= 200:
            raise ValueError("R6 activation audit limit must be between 1 and 200")
        if self.cursor is not None and (
            not isinstance(self.cursor, str) or not self.cursor or len(self.cursor) > 1024
        ):
            raise ValueError("R6 activation audit cursor is invalid")


@dataclass(frozen=True)
class R6ActivationAuditEntry:
    """One verified activation event audit projection."""

    event_ref: R6ActivationEventRef
    authorization_ref: R6ActivationAuthorizationRef
    authorization_hash: str
    scope_ref: R6ActivationScopeRef
    action: R6ActivationAction
    subject: R6ActivationApprovalRef
    rollback_target: R6ActivationApprovalRef | None
    sequence: int
    occurred_at: datetime
    ledger_recorded_at: datetime
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True


@dataclass(frozen=True)
class R6ActivationAuditPage:
    """Deterministic exact-PIT audit page."""

    entries: tuple[R6ActivationAuditEntry, ...]
    next_cursor: str | None
    snapshot_as_of: datetime

    def __post_init__(self) -> None:
        _require_aware(self.snapshot_as_of, "R6 activation audit snapshot_as_of")


class R6ActivationEvidenceQueryRepository(Protocol):
    """Read-only exact-PIT persistence boundary."""

    def get_exact_authorization(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
        expected_hash: str,
        as_of: datetime,
    ) -> R6ActivationAuthorization | None:
        """Return one exact authorization known at the cutoff."""

    def get_exact_event(
        self,
        *,
        event_ref: R6ActivationEventRef,
        as_of: datetime,
    ) -> R6ActivationEvent | None:
        """Return one exact event known at the cutoff."""

    def list_audit(
        self,
        *,
        as_of: datetime,
        cursor: str | None,
        limit: int,
    ) -> R6ActivationAuditPage:
        """Return a cursor-stable exact-PIT audit page."""


class GetExactR6ActivationAuthorization:
    """Resolve an immutable authorization by ID/version/hash and cutoff."""

    def __init__(self, repository: R6ActivationEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR6ActivationAuthorizationCommand,
    ) -> R6ActivationAuthorization | None:
        """Execute the exact authorization query."""

        command.__post_init__()
        return self._repository.get_exact_authorization(
            authorization_ref=command.authorization_ref,
            expected_hash=command.expected_hash,
            as_of=command.as_of,
        )


class GetExactR6ActivationEvent:
    """Resolve an immutable event by ID/version/hash and cutoff."""

    def __init__(self, repository: R6ActivationEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(self, command: GetExactR6ActivationEventCommand) -> R6ActivationEvent | None:
        """Execute the exact event query."""

        command.__post_init__()
        return self._repository.get_exact_event(
            event_ref=command.event_ref,
            as_of=command.as_of,
        )


class AuditR6ActivationEvents:
    """List verified activation evidence through an ID/as-of-only facade."""

    def __init__(self, repository: R6ActivationEvidenceQueryRepository) -> None:
        self._repository = repository

    def execute(self, command: AuditR6ActivationEventsCommand) -> R6ActivationAuditPage:
        """Execute the exact activation audit query."""

        command.__post_init__()
        return self._repository.list_audit(
            as_of=command.as_of,
            cursor=command.cursor,
            limit=command.limit,
        )


__all__ = [
    "AuditR6ActivationEvents",
    "AuditR6ActivationEventsCommand",
    "GetExactR6ActivationAuthorization",
    "GetExactR6ActivationAuthorizationCommand",
    "GetExactR6ActivationEvent",
    "GetExactR6ActivationEventCommand",
    "R6ActivationAuditEntry",
    "R6ActivationAuditPage",
    "R6ActivationEventRef",
    "R6ActivationEvidenceQueryRepository",
]
