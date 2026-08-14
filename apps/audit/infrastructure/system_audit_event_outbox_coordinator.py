"""Same-alias infrastructure coordinator for system audit double writes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from django.db import transaction

from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.system_audit_event import SystemAuditEvent

from .system_audit_outbox_repository import DjangoSystemAuditOutboxRepository
from .system_audit_repository import DjangoSystemAuditEventRepository


class DjangoSystemAuditEventOutboxCoordinator:
    """Coordinate event append and outbox enqueue under one database alias.

    The two repositories keep their own private UOW guards.  They are nested
    inside one coordinator transaction on the same alias, so an event or an
    outbox failure rolls back both writes together.
    """

    __slots__ = ("_event_repository", "_outbox_repository", "_using", "_active")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._event_repository = DjangoSystemAuditEventRepository(using=using)
        self._outbox_repository = DjangoSystemAuditOutboxRepository(using=using)
        self._active = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one non-nested transaction shared by both repositories."""

        if self._active:
            raise SystemAuditEventOutboxConflict("event/outbox UOW cannot be nested")
        self._active = True
        try:
            with transaction.atomic(using=self._using):
                with self._event_repository.atomic():
                    with self._outbox_repository.atomic():
                        yield
        finally:
            self._active = False

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        """Append/replay an event and enqueue its exact canonical payload."""

        persisted_event = self._event_repository.append(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
        )
        outbox_record = self._outbox_repository.enqueue(
            persisted_event,
            created_at=recorded_at,
            available_at=recorded_at,
        )
        if outbox_record.event != persisted_event:
            raise SystemAuditEventOutboxConflict("outbox payload does not match event winner")
        return SystemAuditEventOutboxCommit(
            event=persisted_event,
            outbox_id=outbox_record.outbox_id,
            event_id=persisted_event.event_id,
            idempotency_key=persisted_event.idempotency_key,
        )


__all__ = ["DjangoSystemAuditEventOutboxCoordinator"]
