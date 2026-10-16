"""Data Center-owned port for exact Calendar publication Audit evidence.

This contract contains no Audit application or persistence imports. The Core
integration adapter is the only bridge between these Data Center types and the
Audit-owned event/outbox use cases.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarPublicationAuditPair,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationRecord,
)


class CalendarFormalPublicationAuditPort(Protocol):
    """Publish, replay, or integrity-check one exact formal calendar record."""

    @property
    def database_alias(self) -> str:
        """Return the alias shared with the caller-owned transaction."""

    def record_published(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarPublicationAuditPair:
        """Append one exact publication event and outbox under the live lease."""

    def verify_current_replay(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarPublicationAuditPair:
        """Verify the original actor's unchanged event/outbox under current permission."""

    def verify_published_integrity(
        self,
        record: CalendarFormalPublicationRecord,
        *,
        as_of: datetime,
    ) -> CalendarPublicationAuditPair:
        """Verify the exact persisted pair within an already-authorized DC read UOW."""
