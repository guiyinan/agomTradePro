"""Compose the session adapter, application check, and lock-owning repository."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from rest_framework.request import Request

from apps.data_center.application.calendar_publication_authority import (
    AuthorizeCalendarPublisherUseCase,
    CalendarPublisherSessionRequestProof,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.infrastructure.calendar_publication_authority_repository import (
    DjangoCalendarPublisherAuthorityRepository,
    UtcClock,
)
from apps.data_center.interface.calendar_publication_session_adapter import (
    CalendarPublisherSessionAdapter,
)


def build_calendar_publisher_authorizer(
    *,
    using: str,
    clock: UtcClock | None = None,
) -> AuthorizeCalendarPublisherUseCase:
    """Build a calendar publisher check for one explicit database alias."""

    repository = DjangoCalendarPublisherAuthorityRepository(using=using, clock=clock)
    return AuthorizeCalendarPublisherUseCase(repository)


@contextmanager
def locked_calendar_publisher_for_request(
    request: Request,
    *,
    using: str,
    clock: UtcClock | None = None,
) -> Iterator[LockedCalendarPublisherPrincipal]:
    """Hold the session and explicit permission witnesses for the caller's UoW.

    This context supplies a request actor and authorization proof only. It does
    not publish a calendar, create an audit event, or authorize a trade.
    """

    proof: CalendarPublisherSessionRequestProof = CalendarPublisherSessionAdapter().prove(
        request,
        using=using,
    )
    use_case = build_calendar_publisher_authorizer(using=using, clock=clock)
    with use_case.execute(proof) as principal:
        yield principal


__all__ = [
    "build_calendar_publisher_authorizer",
    "locked_calendar_publisher_for_request",
]
