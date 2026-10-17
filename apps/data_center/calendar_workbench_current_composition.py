"""Compose the workbench's selected-dataset exact current calendar read."""

from __future__ import annotations

from dataclasses import dataclass

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    ReadCurrentCalendarIntent,
)
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchScopeContext,
    CalendarWorkbenchScopeMetadataStatus,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CurrentPublishedExchangeCalendar,
)
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_workbench_scope_context,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    exchange_calendar_publication_key,
)


@dataclass(frozen=True, slots=True)
class CalendarWorkbenchCurrentReadResult:
    """Keep configuration selection and its exact current result together."""

    exchange: str
    scope: CalendarWorkbenchScopeContext
    current: CurrentPublishedExchangeCalendar | None

    def __post_init__(self) -> None:
        """Reject any current row that escaped the selected dataset and exchange."""

        _validate_exchange(self.exchange)
        if type(self.scope) is not CalendarWorkbenchScopeContext:
            raise CalendarPublicationOperationsError(
                "Workbench current result requires typed configuration scope",
                code="CALENDAR_WORKBENCH_CURRENT_RESULT_INVALID",
            )
        self.scope.__post_init__()
        if self.scope.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED:
            if self.current is not None:
                raise CalendarPublicationOperationsError(
                    "Blocked configuration cannot carry an old current calendar",
                    code="CALENDAR_WORKBENCH_CURRENT_RESULT_INVALID",
                )
            return
        metadata = self.scope.metadata
        if metadata is None:
            raise CalendarPublicationOperationsError(
                "Selected configuration has no exact metadata",
                code="CALENDAR_WORKBENCH_CURRENT_RESULT_INVALID",
            )
        if self.current is None:
            return
        if type(self.current) is not CurrentPublishedExchangeCalendar:
            raise CalendarPublicationOperationsError(
                "Current calendar owner returned an invalid result type",
                code="CALENDAR_CURRENT_READ_RESULT_INVALID",
            )
        self.current.__post_init__()
        if (
            self.current.record.seal.dataset.value != metadata.dataset_key
            or self.current.record.seal.exchange != self.exchange
            or self.current.pointer.dataset_key != metadata.dataset_key
        ):
            raise CalendarPublicationOperationsError(
                "Current calendar does not match the selected dataset and exchange",
                code="CALENDAR_CURRENT_READ_SCOPE_MISMATCH",
            )


def read_calendar_workbench_current(exchange: str) -> CalendarWorkbenchCurrentReadResult:
    """Read current reference data for the unique selected calendar dataset.

    The configuration selector and current-publication owner each use their
    existing independently owned default-database transaction. The selected
    dataset is passed unchanged to the exact-current owner; this composition
    does not refresh configuration, reconstruct a pointer or expose a client
    database alias or clock. A blocked selector result is preserved without
    falling back to another or historical dataset.
    """

    _validate_exchange(exchange)
    scope = read_calendar_workbench_scope_context()
    if scope.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED:
        return CalendarWorkbenchCurrentReadResult(
            exchange=exchange,
            scope=scope,
            current=None,
        )
    metadata = scope.metadata
    if metadata is None:
        raise CalendarPublicationOperationsError(
            "Selected configuration has no exact metadata",
            code="CALENDAR_WORKBENCH_CURRENT_SCOPE_INVALID",
        )
    intent = ReadCurrentCalendarIntent(dataset_key=metadata.dataset_key, exchange=exchange)
    current = read_current_exchange_calendar(intent)
    return CalendarWorkbenchCurrentReadResult(exchange=exchange, scope=scope, current=current)


def _validate_exchange(exchange: str) -> None:
    """Validate the exchange token before configuration lookup or current read."""

    if type(exchange) is not str:
        raise CalendarPublicationOperationsError(
            "Current workbench requires one explicit exchange",
            code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            status_code=400,
        )
    try:
        exchange_calendar_publication_key(exchange)
    except CalendarFormalPublicationError as error:
        raise CalendarPublicationOperationsError(
            "Current workbench exchange is invalid",
            code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            status_code=400,
        ) from error


__all__ = [
    "CalendarWorkbenchCurrentReadResult",
    "read_calendar_workbench_current",
]
