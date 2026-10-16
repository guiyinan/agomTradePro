"""Composition root for the explicit calendar audit reader authority."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from rest_framework.request import Request

from apps.data_center.application.calendar_audit_read_authority import (
    AuthorizeCalendarAuditReaderUseCase,
    LockedCalendarAuditReaderPrincipal,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
    UtcClock,
)
from apps.data_center.interface.calendar_audit_reader_session_adapter import (
    CalendarAuditReaderSessionAdapter,
)


def build_calendar_audit_reader_authorizer(
    *,
    using: str,
    clock: UtcClock | None = None,
) -> AuthorizeCalendarAuditReaderUseCase:
    """Build the dedicated read permission check for one explicit alias."""

    repository = DjangoCalendarPublisherAuthorityRepository(using=using, clock=clock)
    return AuthorizeCalendarAuditReaderUseCase(repository)


@contextmanager
def locked_calendar_audit_reader_for_request(
    request: Request,
    *,
    using: str,
    clock: UtcClock | None = None,
) -> Iterator[LockedCalendarAuditReaderPrincipal]:
    """Hold current read-permission witnesses while the caller reads its exact stream.

    This context verifies a GET session and one explicit permission. It does
    not grant publication, append Audit events, or authorize a trade.
    """

    proof = CalendarAuditReaderSessionAdapter().prove(request, using=using)
    use_case = build_calendar_audit_reader_authorizer(using=using, clock=clock)
    with use_case.execute(proof) as principal:
        yield principal


__all__ = [
    "build_calendar_audit_reader_authorizer",
    "locked_calendar_audit_reader_for_request",
]
