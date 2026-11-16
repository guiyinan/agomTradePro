"""Composition entry for exact historical formal-calendar reference reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone

from apps.audit.calendar_publication_composition import (
    build_calendar_publication_audit_coordinator,
)
from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_historical_publication_audit_port import (
    CalendarHistoricalPublicationAuditPort,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    CalendarHistoryClock,
    HistoricalPublishedExchangeCalendar,
    ReadExchangeCalendarPublicationAsOfQuery,
    ReadExchangeCalendarPublicationAsOfUseCase,
)
from apps.data_center.infrastructure.formal_exchange_calendar_publication_history_reader import (
    DjangoFormalExchangeCalendarPublicationHistoryReader,
)
from core.exceptions import DataFetchError
from core.integration.calendar_formal_publication_audit import (
    CoreCalendarFormalPublicationAuditBridge,
)
from core.integration.calendar_formal_publication_history_audit import (
    CoreCalendarFormalPublicationHistoricalAuditBridge,
)


class _ServerClock(CalendarHistoryClock):
    """Read Django's server clock as an exact UTC instant."""

    def now(self) -> datetime:
        """Return the current aware UTC time without normalizing bad values."""

        value = timezone.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise DataFetchError(
                "Calendar history composition clock must be aware UTC",
                code="CALENDAR_PUBLICATION_TIME_INVALID",
            )
        return value.astimezone(UTC)


def read_exchange_calendar_publication_as_of(
    query: ReadExchangeCalendarPublicationAsOfQuery,
) -> HistoricalPublishedExchangeCalendar:
    """Read one exact calendar publication in a composition-owned default UOW.

    This public internal entry does not authorize Audit browsing or infer a
    historical pointer/activation. The returned publication is reference-only
    and must be verified again by any decision composition that consumes it.
    """

    connection = connections[DEFAULT_DB_ALIAS]
    _require_unowned_read_boundary(connection)
    clock = _ServerClock()
    with transaction.atomic(using=DEFAULT_DB_ALIAS):
        audit_coordinator = build_calendar_publication_audit_coordinator(using=DEFAULT_DB_ALIAS)
        publication_audit: CalendarFormalPublicationAuditPort = (
            CoreCalendarFormalPublicationAuditBridge(
                using=DEFAULT_DB_ALIAS,
                coordinator=audit_coordinator,
            )
        )
        historical_audit: CalendarHistoricalPublicationAuditPort = (
            CoreCalendarFormalPublicationHistoricalAuditBridge(
                using=DEFAULT_DB_ALIAS,
                coordinator=audit_coordinator,
            )
        )
        reader = DjangoFormalExchangeCalendarPublicationHistoryReader(
            audit_port=publication_audit,
            historical_audit_port=historical_audit,
            using=DEFAULT_DB_ALIAS,
            clock=clock.now,
        )
        result = ReadExchangeCalendarPublicationAsOfUseCase(
            reader,
            clock=clock,
        ).execute(query)
    return result


def _require_unowned_read_boundary(connection: BaseDatabaseWrapper) -> None:
    """Require one clean default connection before opening the history UOW."""

    if (
        connection.alias != DEFAULT_DB_ALIAS
        or connection.in_atomic_block
        or not connection.get_autocommit()
    ):
        raise DataFetchError(
            "Calendar history composition requires an unowned default database connection",
            code="CALENDAR_HISTORY_TRANSACTION_OWNER_INVALID",
        )


__all__ = ["read_exchange_calendar_publication_as_of"]
