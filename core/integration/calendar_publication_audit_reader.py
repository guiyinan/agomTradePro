"""Core bridge for explicit calendar-audit read authority composition.

This module is the only layer that binds Data Center session authorization to
the Audit-owned selector context. Nothing registers it as an HTTP route or a
default Audit provider.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager

from rest_framework.request import Request

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditDenied,
    CalendarPublicationAuditReadAuthorityProvider,
    CalendarPublicationAuditReaderContext,
)
from apps.data_center.calendar_audit_read_authority_composition import (
    locked_calendar_audit_reader_for_request,
)
from core.exceptions import AuthenticationError


class _DjangoCalendarPublicationAuditReadAuthorityProvider:
    """Bind a current locked Data Center reader principal to Audit selectors."""

    def lock_reader(
        self,
        *,
        request_proof: object,
        dataset_key: str,
        exchange: str,
        database_alias: str,
    ) -> AbstractContextManager[CalendarPublicationAuditReaderContext] | None:
        """Hold the session and exact permission lease for one selector read."""

        if (
            not isinstance(request_proof, Request)
            or type(dataset_key) is not str
            or not dataset_key
            or dataset_key.strip() != dataset_key
            or type(exchange) is not str
            or not exchange
            or exchange.strip() != exchange
            or type(database_alias) is not str
            or not database_alias
            or database_alias.strip() != database_alias
        ):
            raise CalendarPublicationAuditDenied(
                "calendar audit reader requires a real request and exact selector"
            )
        return self._locked_reader(
            request=request_proof,
            dataset_key=dataset_key,
            exchange=exchange,
            database_alias=database_alias,
        )

    @contextmanager
    def _locked_reader(
        self,
        *,
        request: Request,
        dataset_key: str,
        exchange: str,
        database_alias: str,
    ) -> Iterator[CalendarPublicationAuditReaderContext]:
        """Keep the auth lease open and recheck it when a read finishes."""

        with ExitStack() as stack:
            try:
                principal = stack.enter_context(
                    locked_calendar_audit_reader_for_request(
                        request,
                        using=database_alias,
                    )
                )
            except AuthenticationError as error:
                raise CalendarPublicationAuditDenied(
                    "calendar audit reader requires a valid session-authenticated GET"
                ) from error
            context = CalendarPublicationAuditReaderContext._from_authority(
                principal=principal,
                dataset_key=dataset_key,
                exchange=exchange,
            )
            yield context
            context.assert_live()


def build_calendar_publication_audit_read_authority_provider() -> (
    CalendarPublicationAuditReadAuthorityProvider
):
    """Build an explicit provider; no route or module-level default is installed."""

    return _DjangoCalendarPublicationAuditReadAuthorityProvider()


__all__ = ["build_calendar_publication_audit_read_authority_provider"]
