"""Translate real DRF session requests into a price-limit authority proof."""

from __future__ import annotations

from rest_framework.request import Request

from apps.data_center.application.price_limit_publication_authority import (
    PriceLimitPublisherSessionRequestProof,
)
from apps.data_center.interface.calendar_session_request_claim import (
    _prove_session_request_claim,
)


class PriceLimitPublisherSessionAdapter:
    """Accept only session-authenticated management GETs or write POSTs."""

    def prove(
        self,
        request: Request,
        *,
        using: str,
    ) -> PriceLimitPublisherSessionRequestProof:
        """Create a claim for exact lock-time Infrastructure revalidation.

        DRF ``SessionAuthentication`` enforces CSRF on POST before the view
        calls this adapter. GETs are limited to the same explicit permission.
        """

        claim = _prove_session_request_claim(
            request,
            using=using,
            purpose="price_limit_publisher",
        )
        return PriceLimitPublisherSessionRequestProof(
            user_id=claim.user_id,
            session_key=claim.session_key,
            request_authenticated_at=claim.request_authenticated_at,
            request_user_database_alias=claim.request_user_database_alias,
            database_alias=claim.database_alias,
        )


__all__ = ["PriceLimitPublisherSessionAdapter"]
