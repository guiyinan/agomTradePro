"""Audit-owned original pair readback inside a caller's outer transaction."""

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
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
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

_MAX_RETAINED_STREAM_PREFIX = 10_000


def _verify_original_stream_prefix(
    event: SystemAuditEvent, *, scope: AuditScopeRef, using: str
) -> None:
    """Lock and validate only this event's bounded original stream prefix."""
    if event.sequence_no > _MAX_RETAINED_STREAM_PREFIX:
        raise SystemAuditEventOutboxUnavailable("original Audit prefix exceeds the safe read bound")
    rows = tuple(
        SystemAuditEventModel._base_manager.using(using)
        .select_for_update()
        .filter(stream_id=event.stream_id, sequence_no__lte=event.sequence_no)
        .order_by("sequence_no")[: _MAX_RETAINED_STREAM_PREFIX + 1]
    )
    if len(rows) != event.sequence_no:
        raise SystemAuditEventOutboxCorruption("original Audit prefix is incomplete or ambiguous")
    repository = DjangoSystemAuditEventRepository(using=using)
    previous: SystemAuditEvent | None = None
    for sequence, row in enumerate(rows, start=1):
        current = repository._restore(row)
        if (
            current.scope != scope
            or current.sequence_no != sequence
            or current.predecessor_hash != (previous.content_hash if previous is not None else None)
            or (previous is not None and current.recorded_at < previous.recorded_at)
        ):
            raise SystemAuditEventOutboxCorruption("original Audit prefix is disconnected")
        previous = current
    if previous != event:
        raise SystemAuditEventOutboxCorruption("original Audit prefix ends at another event")


def read_retained_system_audit_pair(
    *,
    event_id: str,
    event_version: str,
    stream_id: str,
    scope: AuditScopeRef,
    using: str,
    as_of: datetime,
) -> RetainedSystemAuditPair:
    """Read and lock one exact original pair without append rights or a savepoint.

    The consumer authenticates its own owner before this internal query. This
    method checks the original scope and retained persistence clocks, and never
    substitutes query time for an event or source observation.
    """
    if (
        type(scope) is not AuditScopeRef
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or any(
            type(value) is not str or not value or value != value.strip()
            for value in (event_id, event_version, stream_id, using)
        )
    ):
        raise SystemAuditEventOutboxUnavailable("retained pair selector is invalid")
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using=using)
    try:
        with coordinator.caller_owned_readonly():
            coordinator.lock_streams((stream_id,))
            event = coordinator.get_winner_targeted(
                event_id=event_id, event_version=event_version, as_of=as_of, lock=True
            )
            if event is None:
                raise SystemAuditEventOutboxUnavailable("original Audit event is unavailable")
            if event.scope != scope or event.stream_id != stream_id:
                raise SystemAuditEventOutboxCorruption("original Audit scope or stream differs")
            _verify_original_stream_prefix(event, scope=scope, using=using)
            exact = coordinator.get_exact_outbox_winner_targeted(event)
            if exact is None or exact.event != event:
                raise SystemAuditEventOutboxUnavailable("original exact Outbox is unavailable")
            audit_rows = tuple(
                SystemAuditEventModel._base_manager.using(using)
                .select_for_update()
                .filter(event_id=event_id, event_version=event_version)
                .order_by("pk")[:2]
            )
            outbox_rows = tuple(
                SystemAuditOutboxModel._base_manager.using(using)
                .select_for_update()
                .filter(outbox_id=exact.outbox_id)
                .order_by("outbox_id")[:2]
            )
            if len(audit_rows) != 1 or len(outbox_rows) != 1:
                raise SystemAuditEventOutboxCorruption("original pair metadata is ambiguous")
            row, outbox = audit_rows[0], outbox_rows[0]
            if (
                row.content_hash != event.content_hash
                or row.recorded_at != event.recorded_at
                or row.scope_tenant_id != scope.tenant_id
                or row.scope_owner_id != scope.owner_id
                or outbox.event_id != event.event_id
                or outbox.idempotency_key != event.idempotency_key
                or outbox.payload_hash != exact.payload_hash
            ):
                raise SystemAuditEventOutboxCorruption("original pair metadata differs")
            pair = RetainedSystemAuditPair(
                event=event,
                audit_persisted_at=row.persisted_at,
                outbox_id=str(exact.outbox_id),
                outbox_payload_sha256=exact.payload_hash,
                outbox_created_at=outbox.created_at,
            )
            pair.verify_at_cutoff(as_of=as_of)
            return pair
    except (SystemAuditCorruption, SystemAuditOutboxCorruption) as error:
        raise SystemAuditEventOutboxCorruption("retained pair storage is corrupt") from error
    except (
        SystemAuditUnavailable,
        SystemAuditOutboxUnavailable,
        SystemAuditConflict,
        SystemAuditOutboxConflict,
        DatabaseError,
        ConnectionDoesNotExist,
    ) as error:
        raise SystemAuditEventOutboxUnavailable("retained pair storage is unavailable") from error


__all__ = ("read_retained_system_audit_pair",)
