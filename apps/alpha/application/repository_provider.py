"""Alpha repository providers for application consumers."""

from __future__ import annotations

from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider  # noqa: F401
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider  # noqa: F401
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider  # noqa: F401
from apps.alpha.infrastructure.cache_evaluation import calculate_rolling_metrics  # noqa: F401
from apps.alpha.infrastructure.providers import (
    AlphaAlertRepository,  # noqa: F401
    AlphaPoolDataRepository,  # noqa: F401
    AlphaScoreCacheRepository,  # noqa: F401
    QlibModelRegistryRepository,  # noqa: F401
)
from apps.alpha.infrastructure.qlib_builder import (  # noqa: F401
    TushareQlibBuilder,  # noqa: F401
    inspect_latest_trade_date,  # noqa: F401
    normalize_qlib_symbol,  # noqa: F401
    resolve_effective_trade_date,  # noqa: F401
)
from apps.alpha.infrastructure.scientific_runtime import get_numpy, get_pandas  # noqa: F401


def get_alpha_score_cache_repository():
    """Return the alpha score cache repository."""

    from apps.alpha.infrastructure.providers import AlphaScoreCacheRepository  # noqa: F811

    return AlphaScoreCacheRepository()


def get_qlib_model_registry_repository():
    """Return the qlib model registry repository."""

    from apps.alpha.infrastructure.providers import QlibModelRegistryRepository  # noqa: F811

    return QlibModelRegistryRepository()


def get_alpha_alert_repository():
    """Return the alpha alert repository."""

    from apps.alpha.infrastructure.providers import AlphaAlertRepository  # noqa: F811

    return AlphaAlertRepository()


def get_alpha_pool_data_repository():
    """Return the alpha pool data repository."""

    from apps.alpha.infrastructure.providers import AlphaPoolDataRepository  # noqa: F811

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
