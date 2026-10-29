"""Compose the read-only calendar workbench configuration scope query."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone

from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfiguration,
    CalendarCaptureConfigurationError,
    SelectCalendarCaptureConfigurationUseCase,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarOperationsClock,
)
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchScopeContext,
    ReadCalendarWorkbenchScopeContextUseCase,
)
from apps.data_center.infrastructure.calendar_capture_configuration_repository import (
    DjangoCalendarCaptureConfigurationRepository,
)


class _ServerClock(CalendarOperationsClock):
    """Expose the Django server clock to the workbench scope use case."""

    def now(self) -> datetime:
        """Return the current timezone-aware server instant."""

        return timezone.now()


def read_calendar_workbench_scope_context() -> CalendarWorkbenchScopeContext:
    """Read only the selected calendar metadata inside one owned default transaction.

    The composition never resolves provider credentials, calls a source, or
    reads a current publication pointer. A successful result means metadata was
    selected; it does not establish provider readiness or current publication.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    _require_unowned_default_connection(connection)
    clock = _ServerClock()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        repository = DjangoCalendarCaptureConfigurationRepository()
        selector = SelectCalendarCaptureConfigurationUseCase(repository)
        use_case = ReadCalendarWorkbenchScopeContextUseCase(
            selector=selector,
            clock=clock,
        )
        result = use_case.execute()
    return result


def _require_unowned_default_connection(connection: BaseDatabaseWrapper) -> None:
    """Require autocommit on the fixed alias before opening the sole transaction."""

    if connection.alias != DEFAULT_DB_ALIAS:
        raise CalendarCaptureConfigurationError(
            "Calendar workbench scope requires the configured default database",
            code="CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED",
        )
    if connection.in_atomic_block or not connection.get_autocommit():
        raise CalendarCaptureConfigurationError(
            "Calendar workbench scope must own its outer transaction",
            code="CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED",
        )


def read_calendar_capture_configuration_at(*, as_of: datetime) -> CalendarCaptureConfiguration:
    """Select current metadata at an explicit cutoff without credentials or clock I/O.

    This checks only the currently active catalog rows; it cannot reconstruct
    a historical configuration. The returned dataset still needs a separately
    validated publication for the consumer's exchange and identical cutoff.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    _require_unowned_default_connection(connection)
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        repository = DjangoCalendarCaptureConfigurationRepository()
        return SelectCalendarCaptureConfigurationUseCase(repository).execute(known_at=as_of)


def read_calendar_capture_configuration_reference_at(
    *,
    as_of: datetime,
) -> CalendarCaptureConfiguration:
    """Read metadata at an exact cutoff while reusing one outer transaction.

    Calls without an existing transaction retain the ordinary composition-owned
    read. A locked consumer may reuse exactly one default transaction;
    this path does not create a savepoint or resolve provider credentials.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    if not connection.in_atomic_block:
        return read_calendar_capture_configuration_at(as_of=as_of)
    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.get_autocommit()
        or len(connection.atomic_blocks) != 1
    ):
        code = (
            "CALENDAR_CAPTURE_DATABASE_ALIAS_UNSUPPORTED"
            if connection.alias != DEFAULT_DB_ALIAS
            else "CALENDAR_CAPTURE_CALLER_TRANSACTION_REQUIRED"
        )
        raise CalendarCaptureConfigurationError(
            "Calendar configuration reference requires one default outer transaction",
            code=code,
        )
    repository = DjangoCalendarCaptureConfigurationRepository()
    return SelectCalendarCaptureConfigurationUseCase(repository).execute(known_at=as_of)


__all__ = [
    "read_calendar_capture_configuration_at",
    "read_calendar_capture_configuration_reference_at",
    "read_calendar_workbench_scope_context",
]
