"""Repository providers for filter application consumers."""

from __future__ import annotations

from apps.filter.infrastructure.providers import (
    DjangoFilterRepository as DjangoFilterRepository,
)
from apps.filter.infrastructure.providers import (
    HPFilterAdapter as HPFilterAdapter,
)
from apps.filter.infrastructure.providers import (
    KalmanFilterAdapter as KalmanFilterAdapter,
)


def get_filter_repository() -> DjangoFilterRepository:
    """Return the default filter repository."""

    return DjangoFilterRepository()
