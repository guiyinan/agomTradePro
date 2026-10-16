"""Translate a real DRF session-authenticated request into a typed proof."""

from __future__ import annotations

from rest_framework.request import Request

from apps.data_center.application.calendar_publication_authority import (
    CalendarPublisherSessionRequestProof,
)
from apps.data_center.interface.calendar_session_request_claim import (
    _prove_calendar_session_request,
)


class CalendarPublisherSessionAdapter:
    """Accept only an actual session-authenticated POST request and DB session."""

    def prove(
        self,
        request: Request,
        *,
        using: str,
    ) -> CalendarPublisherSessionRequestProof:
        """Create a claim for infrastructure to revalidate under database locks."""

        claim = _prove_calendar_session_request(request, using=using, purpose="publisher")
        return CalendarPublisherSessionRequestProof(
            user_id=claim.user_id,
            session_key=claim.session_key,
            request_authenticated_at=claim.request_authenticated_at,
            request_user_database_alias=claim.request_user_database_alias,
            database_alias=claim.database_alias,
        )


__all__ = ["CalendarPublisherSessionAdapter"]
