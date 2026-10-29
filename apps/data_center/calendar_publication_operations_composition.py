"""Compose the trusted capture, publication, and current-read entry points."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from rest_framework.request import Request

from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarActivationIdFactory,
    CalendarOperationsClock,
    CalendarPublicationOperationsError,
    CalendarPublicationPreview,
    CapturedExchangeCalendarSnapshot,
    CaptureExchangeCalendarSnapshotIntent,
    ConfirmCalendarPublicationIntent,
    ConfirmCalendarPublicationUseCase,
    PreviewCalendarPublicationIntent,
    PreviewCalendarPublicationUseCase,
    ReadCurrentCalendarIntent,
    ReadCurrentCalendarUseCase,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
    CurrentPublishedExchangeCalendar,
    PublishExchangeCalendarSnapshotUseCase,
    ReadCurrentExchangeCalendarPublicationQuery,
    ReadCurrentExchangeCalendarPublicationUseCase,
)
from apps.data_center.calendar_publication_authority_composition import (
    locked_calendar_publisher_for_request,
)
from apps.data_center.calendar_snapshot_capture_composition import (
    compose_calendar_snapshot_capture,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_repository import (
    DjangoFormalExchangeCalendarPublicationRepository,
)
from core.integration.calendar_formal_publication_audit import (
    CoreCalendarFormalPublicationAuditBridge,
)


class _ServerClock(CalendarOperationsClock):
    """Expose Django's UTC server clock only to composed application use cases."""

    def now(self) -> datetime:
        """Return the current timezone-aware server instant."""

        return timezone.now()


class _ActivationIdFactory(CalendarActivationIdFactory):
    """Mint opaque activation ids internally rather than accepting client ids."""

    def new_id(self) -> str:
        """Return a fresh canonical UUID activation token."""

        return str(uuid4())


def capture_exchange_calendar_snapshot(
    request: Request,
    intent: CaptureExchangeCalendarSnapshotIntent,
) -> CapturedExchangeCalendarSnapshot:
    """Capture one explicit calendar source while publisher authorization is locked.

    The real provider call and persistence join the authority-owned default
    database transaction. The returned receipt is exposed only after that outer
    transaction and its final authorization check exit successfully.
    """

    clock = _ServerClock()
    with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS):
        composition = compose_calendar_snapshot_capture(
            known_at=_require_server_utc(clock.now()),
            using=DEFAULT_DB_ALIAS,
        )
        result = composition.execute(intent)
    return result


def preview_calendar_publication(
    request: Request,
    intent: PreviewCalendarPublicationIntent,
) -> CalendarPublicationPreview:
    """Build a non-persistent publication preview under a live publisher lease."""

    clock = _ServerClock()
    with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS) as principal:
        repository = _formal_repository(clock)
        use_case = PreviewCalendarPublicationUseCase(
            preparation=repository,
            clock=clock,
            activation_ids=_ActivationIdFactory(),
        )
        result = use_case.execute(intent, principal=principal)
    return result


def confirm_calendar_publication(
    request: Request,
    intent: ConfirmCalendarPublicationIntent,
) -> CalendarFormalPublicationCommit:
    """Revalidate and publish an echoed preview under its real locked principal.

    The existing formal publication Application use case owns the writer
    boundary. Its Repository and Core Audit bridge join the authority-owned
    outer transaction; the commit is returned only after the authority context
    exits successfully.
    """

    clock = _ServerClock()
    with locked_calendar_publisher_for_request(request, using=DEFAULT_DB_ALIAS) as principal:
        repository = _formal_repository(clock)
        publisher = PublishExchangeCalendarSnapshotUseCase(repository)
        use_case = ConfirmCalendarPublicationUseCase(
            preparation=repository,
            publisher=publisher,
            clock=clock,
        )
        result = use_case.execute(intent, principal=principal)
    return result


def read_current_exchange_calendar(
    intent: ReadCurrentCalendarIntent,
) -> CurrentPublishedExchangeCalendar | None:
    """Read exact current calendar state in one composition-owned transaction.

    This entry point accepts no request actor, client clock, database alias, or
    publisher proof. An HTTP adapter remains responsible for its own
    authentication policy. The internal Audit check verifies stored publication
    integrity; it does not grant Audit browsing or publishing authority.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    _require_unowned_read_boundary(connection)
    clock = _ServerClock()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        repository = _formal_repository(clock)
        use_case = ReadCurrentCalendarUseCase(reader=repository, clock=clock)
        result = use_case.execute(intent)
    return result


def read_current_exchange_calendar_at(
    query: ReadCurrentExchangeCalendarPublicationQuery,
) -> CurrentPublishedExchangeCalendar:
    """Read the exact current calendar state at the query's unchanged cutoff.

    This internal entry point owns one default-database transaction and composes
    the typed current-publication reader with the same Core Audit bridge used by
    the ordinary current read. It does not call the injected server clock or
    reconstruct a historical pointer.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    _require_unowned_read_boundary(connection)
    clock = _ServerClock()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        repository = _formal_repository(clock)
        use_case = ReadCurrentExchangeCalendarPublicationUseCase(repository)
        result = use_case.execute(query)
    return result


def read_current_exchange_calendar_reference(
    query: ReadCurrentExchangeCalendarPublicationQuery,
) -> CurrentPublishedExchangeCalendar:
    """Verify exact current reference data within one default outer transaction.

    A locked consumer may reuse its sole transaction. Calls without an outer
    transaction retain the ordinary composition-owned read. This grants no
    publication or audit-browsing capability and never creates a savepoint.
    """
    connection = connections[DEFAULT_DB_ALIAS]
    if not connection.in_atomic_block:
        return read_current_exchange_calendar_at(query)
    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.get_autocommit()
        or len(connection.atomic_blocks) != 1
    ):
        raise CalendarPublicationOperationsError(
            "Calendar reference read requires one default outer transaction",
            code="CALENDAR_CURRENT_READ_TRANSACTION_OWNER_INVALID",
            status_code=409,
        )
    repository = _formal_repository(_ServerClock())
    return ReadCurrentExchangeCalendarPublicationUseCase(repository).execute(query)


def _formal_repository(
    clock: CalendarOperationsClock,
) -> DjangoFormalExchangeCalendarPublicationRepository:
    """Build the real same-alias Repository with the public Core Audit bridge."""

    audit_port: CalendarFormalPublicationAuditPort = CoreCalendarFormalPublicationAuditBridge(
        using=DEFAULT_DB_ALIAS
    )
    return DjangoFormalExchangeCalendarPublicationRepository(
        audit_port=audit_port,
        using=DEFAULT_DB_ALIAS,
        clock=clock.now,
    )


def _require_unowned_read_boundary(connection: BaseDatabaseWrapper) -> None:
    """Reject caller-owned transactions so the read composition owns its sole UoW."""

    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.in_atomic_block
        or not connection.get_autocommit()
    ):
        raise CalendarPublicationOperationsError(
            "Current calendar composition requires an unowned default database connection",
            code="CALENDAR_CURRENT_READ_TRANSACTION_OWNER_INVALID",
            status_code=409,
        )


def _require_server_utc(value: datetime) -> datetime:
    """Refuse to pass a naive or non-UTC clock into source selection."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CalendarPublicationOperationsError(
            "Calendar composition server clock must be aware UTC",
            code="CALENDAR_PUBLICATION_TIME_INVALID",
        )
    return value


__all__ = [
    "capture_exchange_calendar_snapshot",
    "confirm_calendar_publication",
    "preview_calendar_publication",
    "read_current_exchange_calendar",
    "read_current_exchange_calendar_at",
    "read_current_exchange_calendar_reference",
]
