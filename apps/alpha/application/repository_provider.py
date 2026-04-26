"""Alpha repository providers for application consumers."""

from __future__ import annotations

from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.cache_evaluation import (
    calculate_rolling_metrics,
    evaluate_model_from_cache,
)
from apps.alpha.infrastructure.providers import (
    AlphaPoolDataRepository,
    AlphaAlertRepository,
    AlphaScoreCacheRepository,
    QlibModelRegistryRepository,
)
from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    normalize_qlib_symbol,
    resolve_effective_trade_date,
)
from apps.alpha.infrastructure.scientific_runtime import get_numpy, get_pandas


def get_alpha_score_cache_repository() -> AlphaScoreCacheRepository:
    """Return the alpha score cache repository."""

    return AlphaScoreCacheRepository()


def get_qlib_model_registry_repository() -> QlibModelRegistryRepository:
    """Return the qlib model registry repository."""

    return QlibModelRegistryRepository()


def get_alpha_alert_repository() -> AlphaAlertRepository:
    """Return the alpha alert repository."""

    return AlphaAlertRepository()


def get_alpha_pool_data_repository() -> AlphaPoolDataRepository:
    """Return the alpha pool data repository."""

    return AlphaPoolDataRepository()


def build_qlib_alpha_provider(*, provider_uri: str, model_path: str, region: str):
    """Build the default qlib alpha provider."""

    from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider

    return QlibAlphaProvider(
        provider_uri=provider_uri,
        model_path=model_path,
        region=region,
    )
