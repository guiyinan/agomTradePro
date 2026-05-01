"""Regime-owned runtime parameter helper.

This module owns reads against ``RiskParameterConfigModel`` so other apps no
longer reach into ``shared.infrastructure.config_helper`` for business config.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import RiskParameterConfigModel

logger = logging.getLogger(__name__)


class ConfigHelper:
    """Convenience accessors for runtime parameter rows."""

    _cache: dict[str, Any] = {}

    @classmethod
    def get_float(
        cls,
        key: str,
        default: float,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True,
    ) -> float:
        value = cls._get_config(key, policy_level, regime, use_cache)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                logger.warning("配置 %s 值 %s 无法转换为浮点数，使用默认值 %s", key, value, default)
        return default

    @classmethod
    def get_int(
        cls,
        key: str,
        default: int,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True,
    ) -> int:
        value = cls._get_config(key, policy_level, regime, use_cache)
        if value is not None:
            try:
                return int(float(value))
            except (TypeError, ValueError):
                logger.warning("配置 %s 值 %s 无法转换为整数，使用默认值 %s", key, value, default)
        return default

    @classmethod
    def get_string(
        cls,
        key: str,
        default: str,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True,
    ) -> str:
        value = cls._get_config(key, policy_level, regime, use_cache)
        if value is not None:
            return str(value)
        return default

    @classmethod
    def get_json(
        cls,
        key: str,
        default: Any,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True,
    ) -> Any:
        cache_key = cls._make_cache_key(key, policy_level, regime)

        if use_cache and cache_key in cls._cache:
            cached = cls._cache[cache_key]
            return default if cached is None else cached

        try:
            config = cls._resolve_config(key, policy_level, regime)
        except Exception as exc:
            logger.error("获取配置 %s 失败: %s", key, exc)
            return default

        if config and config.value_json is not None:
            if use_cache:
                cls._cache[cache_key] = config.value_json
            return config.value_json

        if use_cache:
            cls._cache[cache_key] = None
        return default

    @classmethod
    def _get_config(
        cls,
        key: str,
        policy_level: str,
        regime: str,
        use_cache: bool,
    ) -> Any | None:
        cache_key = cls._make_cache_key(key, policy_level, regime)

        if use_cache and cache_key in cls._cache:
            return cls._cache[cache_key]

        try:
            config = cls._resolve_config(key, policy_level, regime)
        except Exception as exc:
            logger.error("获取配置 %s 失败: %s", key, exc)
            return None

        if config:
            value = config.get_value()
            if use_cache:
                cls._cache[cache_key] = value
            return value

        if use_cache:
            cls._cache[cache_key] = None
        return None

    @staticmethod
    def _resolve_config(
        key: str,
        policy_level: str,
        regime: str,
    ) -> RiskParameterConfigModel | None:
        query = RiskParameterConfigModel._default_manager.filter(
            key=key,
            is_active=True,
        )
        if policy_level:
            query = query.filter(policy_level=policy_level)
        if regime:
            query = query.filter(regime=regime)

        config = query.first()
        if config or (not policy_level and not regime):
            return config

        return RiskParameterConfigModel._default_manager.filter(
            key=key,
            is_active=True,
            policy_level="",
            regime="",
        ).first()

    @staticmethod
    def _make_cache_key(key: str, policy_level: str, regime: str) -> str:
        return f"{key}:{policy_level}:{regime}"

    @classmethod
    def clear_cache(cls) -> None:
        cls._cache.clear()

    @classmethod
    def refresh_cache(cls) -> None:
        cls._cache.clear()


class ConfigKeys:
    """Shared runtime parameter keys now owned by regime config."""

    AI_AUTO_APPROVE_THRESHOLD = "ai.auto_approve_threshold"
    AI_AUTO_REJECT_THRESHOLD = "ai.auto_reject_threshold"
    REGIME_SPREAD_BP_THRESHOLD = "regime.spread_bp_threshold"
    REGIME_US_YIELD_THRESHOLD = "regime.us_yield_threshold"
    REGIME_DAILY_PERSIST_DAYS = "regime.daily_persist_days"
    REGIME_CONFLICT_CONFIDENCE_BOOST = "regime.conflict_confidence_boost"
    REGIME_CONFLICT_DEFAULT_FACTOR = "regime.conflict_default_factor"
    SENTIMENT_NEWS_WEIGHT = "sentiment.news_weight"
    SENTIMENT_POLICY_WEIGHT = "sentiment.policy_weight"
    BACKTEST_RISK_FREE_RATE = "backtest.risk_free_rate"
