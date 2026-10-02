"""Same-alias infrastructure coordinator for system audit double writes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.db import connections, transaction

from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxConflict,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent

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

    @property
    def database_alias(self) -> str:
        """Return the alias shared by the event and outbox repositories."""

        return self._using

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

    @contextmanager
    def caller_owned_atomic(self) -> Iterator[None]:
        """Bind both append capabilities to an existing outer transaction."""

        if self._active:
            raise SystemAuditEventOutboxConflict("event/outbox UOW cannot be nested")
        connection = connections[self._using]
        if not connection.in_atomic_block or connection.get_autocommit():
            raise SystemAuditEventOutboxConflict(
                "caller-owned event/outbox UOW requires an active transaction"
            )
        atomic_blocks = getattr(connection, "atomic_blocks", None)
        if not isinstance(atomic_blocks, list) or len(atomic_blocks) != 1:
            raise SystemAuditEventOutboxConflict(
                "caller-owned event/outbox UOW requires the outermost transaction"
            )
        self._active = True
        try:
            with self._event_repository.caller_owned_atomic():
                with self._outbox_repository.caller_owned_atomic():
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
        """Append and enqueue through bounded activation selectors."""

        persisted_event = self._event_repository.append_targeted(
            event,
            expected_predecessor_hash=expected_predecessor_hash,
            recorded_at=recorded_at,
            scope=scope,
            identity_winner=identity_winner,
            stream_head=stream_head,
        )
        outbox_record = self._outbox_repository.enqueue_targeted(
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

    def lock_stream(self, stream_id: str) -> None:
        """Serialize the exact audit stream before reading its head."""

        self._event_repository.lock_stream(stream_id)

    def lock_streams(self, stream_ids: tuple[str, ...]) -> None:
        """Serialize an exact activation stream group in stable order."""

        self._event_repository.lock_streams(stream_ids)

    def get_activation_group_state_targeted(
        self,
        *,
        identities: tuple[tuple[str, str], ...],
        stream_ids: tuple[str, ...],
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[
        dict[tuple[str, str], SystemAuditEvent],
        dict[str, SystemAuditEvent],
    ]:
        """Lock grouped event winners and stream heads with one bounded read."""

        return self._event_repository.get_activation_group_state_targeted(
            identities=identities,
            stream_ids=stream_ids,
            as_of=as_of,
            scope=scope,
        )

    def append_and_enqueue_group_targeted(
        self,
        events: tuple[SystemAuditEvent, ...],
        *,
        identity_winners: dict[tuple[str, str], SystemAuditEvent],
        stream_heads: dict[str, SystemAuditEvent],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append a serialized event group and enqueue it after one outbox lookup."""

        persisted_events = self._event_repository.append_group_targeted(
            events,
            identity_winners=identity_winners,
            stream_heads=stream_heads,
        )
        replay_events = tuple(
            event
            for event in persisted_events
            if (event.event_id, event.event_version) in identity_winners
        )
        outbox_winners = (
            self._outbox_repository.get_identity_winners_targeted(replay_events)
            if replay_events
            else {}
        )
        outbox_records = self._outbox_repository.enqueue_group_targeted_prefetched(
            persisted_events,
            existing=outbox_winners,
        )
        commits: list[SystemAuditEventOutboxCommit] = []
        for event, outbox_record in zip(persisted_events, outbox_records, strict=True):
            if outbox_record.event != event:
                raise SystemAuditEventOutboxConflict("outbox payload does not match event winner")
            commits.append(
                SystemAuditEventOutboxCommit(
                    event=event,
                    outbox_id=outbox_record.outbox_id,
                    event_id=event.event_id,
                    idempotency_key=event.idempotency_key,
                )
            )
        return tuple(commits)

    def get_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one event identity through the bounded activation selector."""

        return self._event_repository.get_winner_targeted(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
            lock=lock,
        )

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read one stream head through a bounded selector."""

        return self._event_repository.get_current_head_targeted(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
            lock=lock,
        )

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return an existing event identity through the coordinator alias."""

        return self._event_repository.get_winner(
            event_id=event_id,
            event_version=event_version,
            as_of=as_of,
        )

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Return the scoped current head through the coordinator alias."""

        return self._event_repository.get_current_head(
            stream_id=stream_id,
            as_of=as_of,
            scope=scope,
        )


__all__ = ["DjangoSystemAuditEventOutboxCoordinator"]
