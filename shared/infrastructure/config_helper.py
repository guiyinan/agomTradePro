"""
Configuration Helper

提供便捷的配置值获取方法，替代硬编码。
"""

import logging
from functools import lru_cache
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigHelper:
    """
    配置助手类

    从数据库 RiskParameterConfigModel 获取配置值。
    支持缓存以减少数据库查询。
    """

    # 内存缓存
    _cache: dict[str, Any] = {}
    _cache_enabled = True

    @classmethod
    def get_float(
        cls,
        key: str,
        default: float,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True
    ) -> float:
        """
        获取浮点数配置

        Args:
            key: 配置键
            default: 默认值
            policy_level: 政策档位（可选）
            regime: Regime（可选）
            use_cache: 是否使用缓存

        Returns:
            配置值或默认值
        """
        value = cls._get_config(key, policy_level, regime, use_cache)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                logger.warning(f"配置 {key} 值 {value} 无法转换为浮点数，使用默认值 {default}")
        return default

    @classmethod
    def get_int(
        cls,
        key: str,
        default: int,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True
    ) -> int:
        """
        获取整数配置

        Args:
            key: 配置键
            default: 默认值
            policy_level: 政策档位（可选）
            regime: Regime（可选）
            use_cache: 是否使用缓存

        Returns:
            配置值或默认值
        """
        value = cls._get_config(key, policy_level, regime, use_cache)
        if value is not None:
            try:
                return int(float(value))
            except (ValueError, TypeError):
                logger.warning(f"配置 {key} 值 {value} 无法转换为整数，使用默认值 {default}")
        return default

    @classmethod
    def get_string(
        cls,
        key: str,
        default: str,
        policy_level: str = "",
        regime: str = "",
        use_cache: bool = True
    ) -> str:
        """
        获取字符串配置

        Args:
            key: 配置键
            default: 默认值
            policy_level: 政策档位（可选）
            regime: Regime（可选）
            use_cache: 是否使用缓存

        Returns:
            配置值或默认值
        """
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
        use_cache: bool = True
    ) -> Any:
        """
        获取 JSON 配置

        Args:
            key: 配置键
            default: 默认值
            policy_level: 政策档位（可选）
            regime: Regime（可选）
            use_cache: 是否使用缓存

        Returns:
            配置值或默认值
        """
        try:
            from .models import RiskParameterConfigModel

            cache_key = cls._make_cache_key(key, policy_level, regime)

            if use_cache and cache_key in cls._cache:
                return cls._cache[cache_key] if cls._cache[cache_key] is not None else default

            # 尝试精确匹配
            query = RiskParameterConfigModel._default_manager.filter(
                key=key,
                is_active=True
            )

            if policy_level:
                query = query.filter(policy_level=policy_level)
            if regime:
                query = query.filter(regime=regime)

            config = query.first()

            # 如果没有精确匹配，尝试泛化匹配
            if not config and (policy_level or regime):
                config = RiskParameterConfigModel._default_manager.filter(
                    key=key,
                    is_active=True,
                    policy_level="",
                    regime=""
                ).first()

            if config and config.value_json is not None:
                if use_cache:
                    cls._cache[cache_key] = config.value_json
                return config.value_json

            if use_cache:
                cls._cache[cache_key] = None
            return default

        except Exception as e:
            logger.error(f"获取配置 {key} 失败: {e}")
            return default

    @classmethod
    def _get_config(
        cls,
        key: str,
        policy_level: str,
        regime: str,
        use_cache: bool
    ) -> Any | None:
        """内部方法：获取配置值"""
        try:
            from .models import RiskParameterConfigModel

            cache_key = cls._make_cache_key(key, policy_level, regime)

            if use_cache and cache_key in cls._cache:
                return cls._cache[cache_key]

            # 尝试精确匹配
            query = RiskParameterConfigModel._default_manager.filter(
                key=key,
                is_active=True
            )

            if policy_level:
                query = query.filter(policy_level=policy_level)
            if regime:
                query = query.filter(regime=regime)

            config = query.first()

            # 如果没有精确匹配，尝试泛化匹配（空 policy_level 和 regime）
            if not config and (policy_level or regime):
                config = RiskParameterConfigModel._default_manager.filter(
                    key=key,
                    is_active=True,
                    policy_level="",
                    regime=""
                ).first()

            if config:
                value = config.get_value()
                if use_cache:
                    cls._cache[cache_key] = value
                return value

            if use_cache:
                cls._cache[cache_key] = None
            return None

        except Exception as e:
            logger.error(f"获取配置 {key} 失败: {e}")
            return None

    @classmethod
    def _make_cache_key(cls, key: str, policy_level: str, regime: str) -> str:
        """生成缓存键"""
        return f"{key}:{policy_level}:{regime}"

    @classmethod
    def clear_cache(cls):
        """清空缓存"""
        cls._cache.clear()

    @classmethod
    def refresh_cache(cls):
        """刷新缓存（下次访问时重新加载）"""
        cls._cache.clear()


# 便捷函数
def get_config_float(key: str, default: float, **kwargs) -> float:
    """获取浮点数配置"""
    return ConfigHelper.get_float(key, default, **kwargs)


def get_config_int(key: str, default: int, **kwargs) -> int:
    """获取整数配置"""
    return ConfigHelper.get_int(key, default, **kwargs)


def get_config_string(key: str, default: str, **kwargs) -> str:
    """获取字符串配置"""
    return ConfigHelper.get_string(key, default, **kwargs)


# 配置键常量（避免字符串硬编码）
class ConfigKeys:
    """配置键常量"""

    # AI 分类阈值
    AI_AUTO_APPROVE_THRESHOLD = "ai.auto_approve_threshold"
    AI_AUTO_REJECT_THRESHOLD = "ai.auto_reject_threshold"

    # Regime 指标阈值
    REGIME_SPREAD_BP_THRESHOLD = "regime.spread_bp_threshold"
    REGIME_US_YIELD_THRESHOLD = "regime.us_yield_threshold"

    # Regime 信号冲突解决
    REGIME_DAILY_PERSIST_DAYS = "regime.daily_persist_days"
    REGIME_CONFLICT_CONFIDENCE_BOOST = "regime.conflict_confidence_boost"
    REGIME_CONFLICT_DEFAULT_FACTOR = "regime.conflict_default_factor"

    # Sentiment 权重
    SENTIMENT_NEWS_WEIGHT = "sentiment.news_weight"
    SENTIMENT_POLICY_WEIGHT = "sentiment.policy_weight"

    # Backtest 参数
    BACKTEST_RISK_FREE_RATE = "backtest.risk_free_rate"
