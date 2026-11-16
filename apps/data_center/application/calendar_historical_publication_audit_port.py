"""Data Center Application port for historical calendar Audit integrity checks."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarPublicationAuditPair,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalCalendarPublicationRecord,
)


class CalendarHistoricalPublicationAuditPort(Protocol):
    """Verify a published calendar record without requiring current activation."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared by the publication and Audit transaction."""

    def verify_historical_published_integrity(
        self,
        record: HistoricalCalendarPublicationRecord,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Verify the exact original published event and paired outbox row."""


__all__ = ["CalendarHistoricalPublicationAuditPort"]
