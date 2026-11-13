"""Typed original Audit/Outbox evidence; retained clocks grant no current authority."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCorruption
from apps.audit.domain.system_audit_event import SystemAuditEvent


@dataclass(frozen=True, slots=True)
class RetainedSystemAuditPair:
    """One independently checked event and its exact original Outbox metadata."""

    event: SystemAuditEvent
    audit_persisted_at: datetime
    outbox_id: str
    outbox_payload_sha256: str
    outbox_created_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete identities or contradictory original persistence clocks."""
        if type(self.event) is not SystemAuditEvent:
            raise SystemAuditEventOutboxCorruption("retained Audit event is untyped")
        if type(self.outbox_id) is not str:
            raise SystemAuditEventOutboxCorruption("retained Outbox identity is invalid")
        try:
            if str(UUID(self.outbox_id)) != self.outbox_id:
                raise ValueError("noncanonical Outbox identity")
        except ValueError as error:
            raise SystemAuditEventOutboxCorruption("retained Outbox identity is invalid") from error
        digest = self.outbox_payload_sha256
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SystemAuditEventOutboxCorruption("retained Outbox digest is invalid")
        for clock in (self.audit_persisted_at, self.outbox_created_at):
            if type(clock) is not datetime or clock.tzinfo is None or clock.utcoffset() is None:
                raise SystemAuditEventOutboxCorruption("retained persistence clock is naive")
        if not (self.event.recorded_at <= self.audit_persisted_at <= self.outbox_created_at):
            raise SystemAuditEventOutboxCorruption("retained Audit/Outbox clocks disagree")

    def verify_at_cutoff(self, *, as_of: datetime) -> None:
        """Keep every original retained clock within the explicit knowledge cutoff."""
        self.__post_init__()
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise SystemAuditEventOutboxCorruption("retained pair cutoff is naive")
        if max(self.event.recorded_at, self.audit_persisted_at, self.outbox_created_at) > as_of:
            raise SystemAuditEventOutboxCorruption("retained pair is newer than the cutoff")
