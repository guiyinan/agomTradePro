"""Alpha repository providers for application consumers."""

# ruff: noqa: F401, I001

from __future__ import annotations

from typing import Any

from apps.alpha.domain.interfaces import AlphaProvider
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
from apps.alpha.infrastructure.cache_evaluation import calculate_rolling_metrics
from apps.alpha.infrastructure.providers import (
    AlphaAlertRepository,
    AlphaPoolDataRepository,
    AlphaScoreCacheRepository,
    QlibModelRegistryRepository,
)
from apps.alpha.infrastructure.qlib_artifact_runtime import (
    calculate_artifact_hash,
    evaluate_model_metrics,
    save_model_artifact,
    train_qlib_model,
)
from apps.alpha.infrastructure.qlib_builder import (
    TushareQlibBuilder,
    inspect_latest_trade_date,
    normalize_qlib_symbol,
    resolve_effective_trade_date,
)
from apps.alpha.infrastructure.qlib_prediction_runtime import (
    execute_qlib_prediction,
    find_broader_qlib_cache_for_scope,
    normalize_reused_scores,
    reuse_latest_qlib_cache,
    upsert_qlib_cache,
)
from apps.alpha.infrastructure.qlib_runtime_init import (
    build_outdated_qlib_reason,
    build_qlib_runtime_failure_reason,
    cache_is_fresh_for_trade_date,
    extract_model_filename,
    get_qlib_data_latest_date,
    get_runtime_qlib_config,
    install_qlib_pandas_compat,
    make_json_safe,
    normalize_calendar_date,
    normalize_qlib_feature_set_id,
    normalize_qlib_instrument_code,
    normalize_qlib_instrument_list,
    normalize_qlib_region,
    parse_universe_list,
    resolve_qlib_handler_class,
    resolve_qlib_model_path,
    resolve_qlib_stock_list,
)
from apps.alpha.infrastructure.scientific_runtime import get_numpy, get_pandas

__all__ = [
    "AlphaAlertRepository",
    "AlphaPoolDataRepository",
    "AlphaScoreCacheRepository",
    "CacheAlphaProvider",
    "ETFFallbackProvider",
    "QlibModelRegistryRepository",
    "SimpleAlphaProvider",
    "TushareQlibBuilder",
    "build_outdated_qlib_reason",
    "build_qlib_alpha_provider",
    "build_qlib_runtime_failure_reason",
    "cache_is_fresh_for_trade_date",
    "calculate_artifact_hash",
    "calculate_rolling_metrics",
    "evaluate_model_from_cache",
    "evaluate_model_metrics",
    "execute_qlib_prediction",
    "extract_model_filename",
    "find_broader_qlib_cache_for_scope",
    "get_alpha_alert_repository",
    "get_alpha_pool_data_repository",
    "get_alpha_score_cache_repository",
    "get_numpy",
    "get_pandas",
    "get_qlib_data_latest_date",
    "get_qlib_model_registry_repository",
    "get_runtime_qlib_config",
    "inspect_latest_trade_date",
    "install_qlib_pandas_compat",
    "make_json_safe",
    "normalize_calendar_date",
    "normalize_qlib_feature_set_id",
    "normalize_qlib_instrument_code",
    "normalize_qlib_instrument_list",
    "normalize_qlib_region",
    "normalize_qlib_symbol",
    "normalize_reused_scores",
    "parse_universe_list",
    "resolve_effective_trade_date",
    "resolve_qlib_handler_class",
    "resolve_qlib_model_path",
    "resolve_qlib_stock_list",
    "reuse_latest_qlib_cache",
    "save_model_artifact",
    "train_qlib_model",
    "upsert_qlib_cache",
]


def get_alpha_score_cache_repository() -> AlphaScoreCacheRepository:
    """Return the alpha score cache repository."""

    from apps.alpha.infrastructure.providers import AlphaScoreCacheRepository  # noqa: F811

    return AlphaScoreCacheRepository()


def get_qlib_model_registry_repository() -> QlibModelRegistryRepository:
    """Return the qlib model registry repository."""

    from apps.alpha.infrastructure.providers import QlibModelRegistryRepository  # noqa: F811

    return QlibModelRegistryRepository()


def get_alpha_alert_repository() -> AlphaAlertRepository:
    """Return the alpha alert repository."""

    from apps.alpha.infrastructure.providers import AlphaAlertRepository  # noqa: F811

    return AlphaAlertRepository()


def get_alpha_pool_data_repository() -> AlphaPoolDataRepository:
    """Return the alpha pool data repository."""

    from apps.alpha.infrastructure.providers import AlphaPoolDataRepository  # noqa: F811

    return AlphaPoolDataRepository()


def evaluate_model_from_cache(*args: Any, **kwargs: Any) -> Any:
    """Evaluate cached model predictions through the infrastructure evaluator."""

    from apps.alpha.infrastructure.cache_evaluation import evaluate_model_from_cache as _impl

    return _impl(*args, **kwargs)


def build_qlib_alpha_provider(*, provider_uri: str, model_path: str, region: str) -> AlphaProvider:
    """Build the default qlib alpha provider."""

    from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider

    return QlibAlphaProvider(
        provider_uri=provider_uri,
        model_path=model_path,
        region=region,
    )
