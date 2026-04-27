"""Alpha repository providers for application consumers."""

from __future__ import annotations

from apps.alpha.infrastructure.providers import (
    AlphaAlertRepository,
    AlphaPoolDataRepository,
    AlphaScoreCacheRepository,
    QlibModelRegistryRepository,
)
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.cache_evaluation import calculate_rolling_metrics
from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    normalize_qlib_symbol,
    resolve_effective_trade_date,
)
from apps.alpha.infrastructure.scientific_runtime import get_numpy, get_pandas


def get_alpha_score_cache_repository():
    """Return the alpha score cache repository."""

    from apps.alpha.infrastructure.providers import AlphaScoreCacheRepository

    return AlphaScoreCacheRepository()


def get_qlib_model_registry_repository():
    """Return the qlib model registry repository."""

    from apps.alpha.infrastructure.providers import QlibModelRegistryRepository

    return QlibModelRegistryRepository()


def get_alpha_alert_repository():
    """Return the alpha alert repository."""

    from apps.alpha.infrastructure.providers import AlphaAlertRepository

    return AlphaAlertRepository()


def get_alpha_pool_data_repository():
    """Return the alpha pool data repository."""

    from apps.alpha.infrastructure.providers import AlphaPoolDataRepository

    return AlphaPoolDataRepository()


def evaluate_model_from_cache(*args, **kwargs):
    """Evaluate cached model predictions through the infrastructure evaluator."""

    from apps.alpha.infrastructure.cache_evaluation import evaluate_model_from_cache as _impl

    return _impl(*args, **kwargs)


def build_qlib_alpha_provider(*, provider_uri: str, model_path: str, region: str):
    """Build the default qlib alpha provider."""

    from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider

    return QlibAlphaProvider(
        provider_uri=provider_uri,
        model_path=model_path,
        region=region,
    )
