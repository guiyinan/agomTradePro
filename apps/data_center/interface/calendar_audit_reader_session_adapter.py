"""Translate a real DRF session-authenticated GET into a reader proof."""

from __future__ import annotations

from rest_framework.request import Request

from apps.data_center.application.calendar_audit_read_authority import (
    CalendarAuditReaderSessionRequestProof,
)
from apps.data_center.interface.calendar_session_request_claim import (
    _prove_calendar_session_request,
)


class CalendarAuditReaderSessionAdapter:
    """Accept only an actual session-authenticated GET and DB session."""

    def prove(
        self,
        request: Request,
        *,
        using: str,
    ) -> CalendarAuditReaderSessionRequestProof:
        """Create a claim for Infrastructure to revalidate under database locks."""

        claim = _prove_calendar_session_request(request, using=using, purpose="audit_reader")
        return CalendarAuditReaderSessionRequestProof(
            user_id=claim.user_id,
            session_key=claim.session_key,
            request_authenticated_at=claim.request_authenticated_at,
            request_user_database_alias=claim.request_user_database_alias,
            database_alias=claim.database_alias,
        )


__all__ = ["CalendarAuditReaderSessionAdapter"]
