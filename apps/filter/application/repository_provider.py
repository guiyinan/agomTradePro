"""Repository providers for filter application consumers."""

from __future__ import annotations

from apps.filter.infrastructure.providers import (
    DjangoFilterRepository,
    HPFilterAdapter,
    KalmanFilterAdapter,
)


def get_filter_repository() -> DjangoFilterRepository:
    """Return the default filter repository."""

    return DjangoFilterRepository()
