"""Alpha repository providers for application consumers."""

from __future__ import annotations

from apps.alpha.infrastructure.repositories import (
    AlphaAlertRepository,
    AlphaScoreCacheRepository,
    QlibModelRegistryRepository,
)


def get_alpha_score_cache_repository() -> AlphaScoreCacheRepository:
    """Return the alpha score cache repository."""

    return AlphaScoreCacheRepository()


def get_qlib_model_registry_repository() -> QlibModelRegistryRepository:
    """Return the qlib model registry repository."""

    return QlibModelRegistryRepository()


def get_alpha_alert_repository() -> AlphaAlertRepository:
    """Return the alpha alert repository."""

    return AlphaAlertRepository()
