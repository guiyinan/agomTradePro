"""Read a bounded complete original stream in the caller's outer transaction."""

from datetime import datetime

from django.db import DatabaseError
from django.utils.connection import ConnectionDoesNotExist

from apps.audit.application.retained_system_audit_pair import RetainedSystemAuditPair
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCorruption,
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
    SystemAuditOutboxConflict,
    SystemAuditOutboxCorruption,
    SystemAuditOutboxUnavailable,
)
from apps.audit.infrastructure.system_audit_repository import (
    DjangoSystemAuditEventRepository,
    SystemAuditConflict,
    SystemAuditCorruption,
    SystemAuditUnavailable,
)

_MAX_STREAM_EVENTS = 10_000
_OUTBOX_BATCH_SIZE = 100


def read_retained_system_audit_stream(
    *, stream_id: str, scope: AuditScopeRef, using: str, as_of: datetime
) -> tuple[RetainedSystemAuditPair, ...]:
    """Verify every original pair in one selected knowable stream prefix.

    Consumers authenticate their own read scope. This internal reader joins
    their outer transaction and locks the selected stream without granting
    append rights. Oversized, disconnected, cross-scope or incomplete prefixes
    fail in full. It never substitutes another stream or repairs missing rows.
    """
    if (
        type(scope) is not AuditScopeRef
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or any(
            type(value) is not str or not value or value != value.strip()
            for value in (stream_id, using)
        )
    ):
        raise SystemAuditEventOutboxUnavailable("retained stream selector is invalid")
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using=using)
    try:
        with coordinator.caller_owned_readonly():
            coordinator.lock_streams((stream_id,))
            return _read_locked_stream(stream_id=stream_id, scope=scope, using=using, as_of=as_of)
    except (SystemAuditCorruption, SystemAuditOutboxCorruption) as error:
        raise SystemAuditEventOutboxCorruption("retained stream storage is corrupt") from error
    except (
        SystemAuditUnavailable,
        SystemAuditOutboxUnavailable,
        SystemAuditConflict,
        SystemAuditOutboxConflict,
        DatabaseError,
        ConnectionDoesNotExist,
    ) as error:
        raise SystemAuditEventOutboxUnavailable("retained stream storage is unavailable") from error


def _read_locked_stream(
    *, stream_id: str, scope: AuditScopeRef, using: str, as_of: datetime
) -> tuple[RetainedSystemAuditPair, ...]:
    rows = tuple(
        SystemAuditEventModel._base_manager.using(using)
        .select_for_update()
        .filter(stream_id=stream_id, recorded_at__lte=as_of)
        .order_by("sequence_no")[: _MAX_STREAM_EVENTS + 1]
    )
    if len(rows) > _MAX_STREAM_EVENTS:
        raise SystemAuditEventOutboxUnavailable("retained stream exceeds the technical read bound")
    repository = DjangoSystemAuditEventRepository(using=using)
    events: list[SystemAuditEvent] = []
    previous: SystemAuditEvent | None = None
    for sequence, row in enumerate(rows, start=1):
        event = repository._restore(row)
        if (
            event.stream_id != stream_id
            or event.scope != scope
            or event.sequence_no != sequence
            or event.predecessor_hash != (previous.content_hash if previous is not None else None)
            or (previous is not None and event.recorded_at < previous.recorded_at)
            or event.recorded_at > as_of
        ):
            raise SystemAuditEventOutboxCorruption("retained stream prefix is disconnected")
        events.append(event)
        previous = event
    outbox = DjangoSystemAuditOutboxRepository(using=using)
    pairs: list[RetainedSystemAuditPair] = []
    for start in range(0, len(events), _OUTBOX_BATCH_SIZE):
        batch = tuple(events[start : start + _OUTBOX_BATCH_SIZE])
        winners = outbox.get_identity_winners_targeted(batch)
        if len(winners) != len(batch):
            raise SystemAuditEventOutboxUnavailable("original stream Outbox pair is unavailable")
        for offset, event in enumerate(batch):
            winner = winners.get(event.event_id)
            if winner is None or winner.event != event:
                raise SystemAuditEventOutboxCorruption("original stream Outbox pair differs")
            # The Outbox repository independently restores its original row,
            # including exact payload_hash == event.content_hash validation.
            pair = RetainedSystemAuditPair(
                event=event,
                audit_persisted_at=rows[start + offset].persisted_at,
                outbox_id=str(winner.outbox_id),
                outbox_payload_sha256=winner.event.content_hash,
                outbox_created_at=winner.created_at,
            )
            pair.verify_at_cutoff(as_of=as_of)
            pairs.append(pair)
    return tuple(pairs)


__all__ = ("read_retained_system_audit_stream",)
