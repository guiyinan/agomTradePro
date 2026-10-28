"""Compatibility facade for fixed Calendar publisher and reader grants."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from apps.data_center.application.calendar_audit_read_authority import (
    CalendarAuditReaderSessionRequestProof,
    LockedCalendarAuditReaderPrincipal,
)
from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.infrastructure._session_grant_authority_kernel import (
    SessionGrantAuthorityKernel,
    UtcClock,
)
from core.exceptions import InvalidInputError


class DjangoCalendarPublisherAuthorityRepository:
    """Keep the public Calendar repository while delegating shared lock logic."""

    def __init__(self, *, using: str, clock: UtcClock | None = None) -> None:
        """Bind the Calendar authority facade to one database alias and clock."""

        if type(using) is not str or not using or using.strip() != using:
            raise InvalidInputError(
                "Calendar publisher repository requires a database alias",
                code="CALENDAR_PUBLISHER_ALIAS_INVALID",
            )
        self._kernel = SessionGrantAuthorityKernel(using=using, clock=clock)

    @contextmanager
    def locked_calendar_publisher(
        self,
        proof: CalendarPublisherSessionRequestProof,
    ) -> Iterator[LockedCalendarPublisherPrincipal]:
        """Hold a Calendar publication grant and session witnesses under lock."""

        with self._kernel.locked_calendar_publisher(proof) as principal:
            yield principal

    @contextmanager
    def locked_calendar_audit_reader(
        self,
        proof: CalendarAuditReaderSessionRequestProof,
    ) -> Iterator[LockedCalendarAuditReaderPrincipal]:
        """Hold the existing dedicated Calendar audit-read grant under lock."""

        with self._kernel.locked_calendar_audit_reader(proof) as principal:
            yield principal


__all__ = ["DjangoCalendarPublisherAuthorityRepository", "UtcClock"]
