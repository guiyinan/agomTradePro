"""Infrastructure repository for the fixed price-limit publication grant."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from apps.data_center.application.price_limit_publication_authority import (
    LockedPriceLimitPublisherPrincipal,
    PriceLimitPublisherSessionRequestProof,
)
from apps.data_center.infrastructure._session_grant_authority_kernel import (
    SessionGrantAuthorityKernel,
    UtcClock,
)
from core.exceptions import InvalidInputError


class DjangoPriceLimitPublisherAuthorityRepository:
    """Revalidate the exact PriceLimit permission using the shared lock kernel."""

    def __init__(self, *, using: str, clock: UtcClock | None = None) -> None:
        """Bind the fixed price-limit authority check to one database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise InvalidInputError(
                "Price-limit publisher repository requires a database alias",
                code="PRICE_LIMIT_PUBLISHER_ALIAS_INVALID",
            )
        self._kernel = SessionGrantAuthorityKernel(using=using, clock=clock)

    @contextmanager
    def locked_price_limit_publisher(
        self,
        proof: PriceLimitPublisherSessionRequestProof,
    ) -> Iterator[LockedPriceLimitPublisherPrincipal]:
        """Hold the exact session, identity, and price-limit grant under lock."""

        with self._kernel.locked_price_limit_publisher(proof) as principal:
            yield principal


__all__ = ["DjangoPriceLimitPublisherAuthorityRepository"]
