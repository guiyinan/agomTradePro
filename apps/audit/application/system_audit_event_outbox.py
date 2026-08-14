"""Atomic system-audit event plus outbox application contract.

The contract intentionally accepts a fully validated ``SystemAuditEvent`` and
delegates the transaction boundary to one injected writer.  It does not know
about Django, data-center providers, or publisher side effects.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from apps.audit.domain.system_audit_event import SystemAuditEvent


class SystemAuditEventOutboxUnavailable(Exception):
    """The atomic event/outbox writer is unavailable."""


class SystemAuditEventOutboxConflict(Exception):
    """The event or outbox identity conflicts with an existing winner."""


class SystemAuditEventOutboxCorruption(Exception):
    """The writer returned a non-exact event/outbox pair."""


@dataclass(frozen=True, slots=True)
class SystemAuditEventOutboxCommit:
    """The exact pair committed by one atomic writer."""

    event: SystemAuditEvent
    outbox_id: UUID
    event_id: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.event.event_id != self.event_id:
            raise ValueError("event_id must match the committed event")
        if self.event.idempotency_key != self.idempotency_key:
            raise ValueError("idempotency_key must match the committed event")


class SystemAuditEventOutboxWriter(Protocol):
    """One-alias transaction boundary for event and outbox persistence."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open a non-nested transaction shared by event and outbox writes."""

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        """Append the event and enqueue the exact same payload atomically."""


@dataclass(frozen=True, slots=True)
class AppendSystemAuditEventOutboxCommand:
    """ID/hash-bound event append request."""

    event: SystemAuditEvent
    expected_predecessor_hash: str | None
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.event.recorded_at != self.recorded_at:
            raise ValueError("event.recorded_at must equal recorded_at")


class AppendSystemAuditEventOutboxUseCase:
    """Persist one event and its outbox delivery record as one unit."""

    __slots__ = ("_writer",)

    def __init__(self, writer: SystemAuditEventOutboxWriter) -> None:
        self._writer = writer

    def execute(self, command: AppendSystemAuditEventOutboxCommand) -> SystemAuditEventOutboxCommit:
        """Append/replay the exact event/outbox pair without partial commits."""

        try:
            with self._writer.atomic():
                commit = self._writer.append_and_enqueue(
                    command.event,
                    expected_predecessor_hash=command.expected_predecessor_hash,
                    recorded_at=command.recorded_at,
                )
        except (SystemAuditEventOutboxConflict, SystemAuditEventOutboxCorruption):
            raise
        except Exception as error:
            raise SystemAuditEventOutboxUnavailable(
                "atomic system audit event/outbox append failed"
            ) from error
        if commit.event != command.event:
            raise SystemAuditEventOutboxCorruption("writer substituted the event winner")
        return commit


__all__ = [
    "AppendSystemAuditEventOutboxCommand",
    "AppendSystemAuditEventOutboxUseCase",
    "SystemAuditEventOutboxCommit",
    "SystemAuditEventOutboxConflict",
    "SystemAuditEventOutboxCorruption",
    "SystemAuditEventOutboxUnavailable",
    "SystemAuditEventOutboxWriter",
]
