"""Compose the read-only calendar workbench configuration scope query."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone

from apps.data_center.application.calendar_capture_configuration import (
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


__all__ = ["read_calendar_workbench_scope_context"]
