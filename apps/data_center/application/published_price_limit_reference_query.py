"""Purpose-limited read of published price-limit reference history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationReadResult,
    PriceLimitPublicationScope,
    require_utc,
)
from core.exceptions import InvalidInputError


class PublishedPriceLimitReferenceReadPort(Protocol):
    """Read one exact market scope after verifying its original source and history."""

    def read_published_reference(
        self,
        scope: PriceLimitPublicationScope,
        *,
        as_of: datetime,
        server_now: datetime,
    ) -> PriceLimitPublicationReadResult | None:
        """Resolve the reference visible at a required server-known cutoff."""


class ReadPublishedPriceLimitReferenceUseCase:
    """Read price-limit reference history without creating a publisher capability."""

    def __init__(
        self,
        reader: PublishedPriceLimitReferenceReadPort,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind the narrow query to its persistence reader and actual server clock."""

        self._reader = reader
        self._clock = clock

    def execute(
        self,
        scope: PriceLimitPublicationScope,
        *,
        as_of: datetime,
    ) -> PriceLimitPublicationReadResult | None:
        """Resolve only the supplied market scope at a nonfuture UTC knowledge time."""

        if type(scope) is not PriceLimitPublicationScope:
            raise InvalidInputError(
                "Explicit market scope required", code="PRICE_LIMIT_SCOPE_INVALID"
            )
        scope.__post_init__()
        require_utc(as_of)
        server_now = self._clock()
        require_utc(server_now)
        if as_of > server_now:
            raise InvalidInputError("Future cutoff unavailable", code="PRICE_LIMIT_FUTURE_CUTOFF")
        result = self._reader.read_published_reference(
            scope,
            as_of=as_of,
            server_now=server_now,
        )
        if result is not None and (
            type(result) is not PriceLimitPublicationReadResult
            or result.as_of != as_of
            or result.record.seal.publication_key != scope.publication_key
            or result.record.first_published_at > as_of
        ):
            raise InvalidInputError(
                "Published price-limit reader returned another scope or cutoff",
                code="PRICE_LIMIT_REFERENCE_RESULT_INVALID",
            )
        return result


__all__ = [
    "PublishedPriceLimitReferenceReadPort",
    "ReadPublishedPriceLimitReferenceUseCase",
]
