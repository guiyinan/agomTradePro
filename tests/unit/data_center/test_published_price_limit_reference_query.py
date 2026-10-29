"""Cutoff and scope contracts for the purpose-limited PriceLimit read query."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationScope,
)
from apps.data_center.application.published_price_limit_reference_query import (
    ReadPublishedPriceLimitReferenceUseCase,
)
from core.exceptions import InvalidInputError

_NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


class _Reader:
    """Record the one exact application query issued by the use case."""

    def __init__(self) -> None:
        self.calls: list[tuple[PriceLimitPublicationScope, datetime, datetime]] = []

    def read_published_reference(
        self,
        scope: PriceLimitPublicationScope,
        *,
        as_of: datetime,
        server_now: datetime,
    ) -> None:
        self.calls.append((scope, as_of, server_now))
        return None


def _scope() -> PriceLimitPublicationScope:
    return PriceLimitPublicationScope(7, "tushare", "600000.SH", date(2026, 10, 28))


def test_reference_query_passes_required_scope_cutoff_and_actual_server_clock() -> None:
    reader = _Reader()
    as_of = _NOW - timedelta(minutes=1)

    result = ReadPublishedPriceLimitReferenceUseCase(reader, clock=lambda: _NOW).execute(
        _scope(), as_of=as_of
    )

    assert result is None
    assert reader.calls == [(_scope(), as_of, _NOW)]


def test_reference_query_rejects_future_cutoff_before_persistence_read() -> None:
    reader = _Reader()

    with pytest.raises(InvalidInputError, match="Future cutoff"):
        ReadPublishedPriceLimitReferenceUseCase(reader, clock=lambda: _NOW).execute(
            _scope(), as_of=_NOW + timedelta(microseconds=1)
        )

    assert reader.calls == []
