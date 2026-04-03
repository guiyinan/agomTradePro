"""
Cache Service Infrastructure Layer

Provides unified caching service for Regime calculations and macro data.
Supports Redis as backend with fallback to in-memory cache.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CacheService:
    """
    统一缓存服务

    提供：
    1. Regime计算结果缓存（15分钟）
    2. 宏观数据序列缓存（15分钟）
    3. AI建议缓存（1小时）
    4. 通用缓存接口
    """

    # 缓存键前缀
    PREFIX_REGIME = "regime"
    PREFIX_MACRO_SERIES = "macro_series"
    PREFIX_AI_INSIGHTS = "ai_insights"
    PREFIX_ALLOCATION = "allocation"

    # 默认缓存时间（秒）
    TTL_REGIME = 900  # 15分钟
    TTL_MACRO_SERIES = 900  # 15分钟
    TTL_AI_INSIGHTS = 3600  # 1小时
    TTL_ALLOCATION = 600  # 10分钟

    @classmethod
    def _make_key(cls, prefix: str, **kwargs) -> str:
        """
        生成缓存键

        Args:
            prefix: 键前缀
            **kwargs: 键参数

        Returns:
            str: 格式化的缓存键
        """
        # 将参数排序后生成哈希
        parts = sorted(f"{k}={v}" for k, v in kwargs.items())
        key_string = ":".join(parts)
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()[:8]

        return f"{prefix}:{key_hash}"

    @classmethod
    def get_regime(
        cls,
        as_of_date: str,
        growth_indicator: str,
        inflation_indicator: str,
    ) -> dict | None:
        """
        获取缓存的Regime计算结果

        Args:
            as_of_date: 计算日期
            growth_indicator: 增长指标代码
            inflation_indicator: 通胀指标代码

        Returns:
            Dict: 缓存的Regime数据，未命中返回None
        """
        key = cls._make_key(
            cls.PREFIX_REGIME,
            date=as_of_date,
            growth=growth_indicator,
            inflation=inflation_indicator,
        )

        data = cache.get(key)
        if data:
            logger.debug(f"Regime缓存命中: {key}")

        return data

    @classmethod
    def set_regime(
        cls,
        as_of_date: str,
        growth_indicator: str,
        inflation_indicator: str,
        data: dict,
        timeout: int | None = None,
    ) -> bool:
        """
        设置Regime计算结果缓存

        Args:
            as_of_date: 计算日期
            growth_indicator: 增长指标代码
            inflation_indicator: 通胀指标代码
            data: 要缓存的数据
            timeout: 缓存时间（秒），None表示使用默认值

        Returns:
            bool: 是否成功
        """
        key = cls._make_key(
            cls.PREFIX_REGIME,
            date=as_of_date,
            growth=growth_indicator,
            inflation=inflation_indicator,
        )

        timeout = timeout or cls.TTL_REGIME
        result = cache.set(key, data, timeout=timeout)

        if result:
            logger.debug(f"Regime缓存已设置: {key}, TTL={timeout}s")

        return result

    @classmethod
    def get_macro_series(
        cls,
        indicator_code: str,
        end_date: str,
    ) -> dict | None:
        """
        获取缓存的宏观数据序列

        Args:
            indicator_code: 指标代码
            end_date: 结束日期

        Returns:
            Dict: 缓存的数据，未命中返回None
        """
        key = cls._make_key(
            cls.PREFIX_MACRO_SERIES,
            indicator=indicator_code,
            end_date=end_date,
        )

        data = cache.get(key)
        if data:
            logger.debug(f"宏观数据缓存命中: {key}")

        return data

    @classmethod
    def set_macro_series(
        cls,
        indicator_code: str,
        end_date: str,
        data: dict,
        timeout: int | None = None,
    ) -> bool:
        """
        设置宏观数据序列缓存

        Args:
            indicator_code: 指标代码
            end_date: 结束日期
            data: 要缓存的数据
            timeout: 缓存时间（秒）

        Returns:
            bool: 是否成功
        """
        key = cls._make_key(
            cls.PREFIX_MACRO_SERIES,
            indicator=indicator_code,
            end_date=end_date,
        )

        timeout = timeout or cls.TTL_MACRO_SERIES
        result = cache.set(key, data, timeout=timeout)

        if result:
            logger.debug(f"宏观数据缓存已设置: {key}, TTL={timeout}s")

        return result

    @classmethod
    def get_ai_insights(
        cls,
        regime: str,
        match_score: float,
        invested_ratio: float,
    ) -> dict | None:
        """
        获取缓存的AI建议

        Args:
            regime: 当前Regime
            match_score: 匹配度分数
            invested_ratio: 仓位比例

        Returns:
            Dict: 缓存的建议，未命中返回None
        """
        key = cls._make_key(
            cls.PREFIX_AI_INSIGHTS,
            regime=regime,
            score=f"{match_score:.0f}",
            ratio=f"{invested_ratio:.2f}",
        )

        data = cache.get(key)
        if data:
            logger.debug(f"AI建议缓存命中: {key}")

        return data

    @classmethod
    def set_ai_insights(
        cls,
        regime: str,
        match_score: float,
        invested_ratio: float,
        data: dict,
        timeout: int | None = None,
    ) -> bool:
        """
        设置AI建议缓存

        Args:
            regime: 当前Regime
            match_score: 匹配度分数
            invested_ratio: 仓位比例
            data: 要缓存的数据
            timeout: 缓存时间（秒）

        Returns:
            bool: 是否成功
        """
        key = cls._make_key(
            cls.PREFIX_AI_INSIGHTS,
            regime=regime,
            score=f"{match_score:.0f}",
            ratio=f"{invested_ratio:.2f}",
        )

        timeout = timeout or cls.TTL_AI_INSIGHTS
        result = cache.set(key, data, timeout=timeout)

        if result:
            logger.debug(f"AI建议缓存已设置: {key}, TTL={timeout}s")

        return result

    @classmethod
    def get_allocation_advice(
        cls,
        regime: str,
        risk_profile: str,
        policy_level: str,
    ) -> dict | None:
        """
        获取缓存的资产配置建议

        Args:
            regime: 当前Regime
            risk_profile: 风险偏好
            policy_level: 政策档位

        Returns:
            Dict: 缓存的建议，未命中返回None
        """
        key = cls._make_key(
            cls.PREFIX_ALLOCATION,
            regime=regime,
            risk=risk_profile,
            policy=policy_level,
        )

        data = cache.get(key)
        if data:
            logger.debug(f"配置建议缓存命中: {key}")

        return data

    @classmethod
    def set_allocation_advice(
        cls,
        regime: str,
        risk_profile: str,
        policy_level: str,
        data: dict,
        timeout: int | None = None,
    ) -> bool:
        """
        设置资产配置建议缓存

        Args:
            regime: 当前Regime
            risk_profile: 风险偏好
            policy_level: 政策档位
            data: 要缓存的数据
            timeout: 缓存时间（秒）

        Returns:
            bool: 是否成功
        """
        key = cls._make_key(
            cls.PREFIX_ALLOCATION,
            regime=regime,
            risk=risk_profile,
            policy=policy_level,
        )

        timeout = timeout or cls.TTL_ALLOCATION
        result = cache.set(key, data, timeout=timeout)

        if result:
            logger.debug(f"配置建议缓存已设置: {key}, TTL={timeout}s")

        return result

    @classmethod
    def invalidate_regime(cls) -> bool:
        """
        清除所有Regime相关缓存

        Returns:
            bool: 是否成功
        """
        try:
            # Django cache的clear()会清除所有缓存
            # 这里只清除Regime前缀的缓存需要使用自定义实现
            # 简化版：清除所有缓存
            cache.clear()
            logger.info("已清除Regime相关缓存")
            return True
        except Exception as e:
            logger.error(f"清除Regime缓存失败: {e}")
            return False

    @classmethod
    def get_cache_info(cls) -> dict:
        """
        获取缓存信息（用于监控）

        Returns:
            Dict: 缓存统计信息
        """
        info = {
            "backend": settings.CACHES["default"]["BACKEND"],
            "default_timeout": cache.default_timeout,
        }

        # 如果使用Redis，获取额外信息
        try:
            from django.core.cache.backends.redis import RedisCache
            if isinstance(cache, RedisCache):
                info["type"] = "redis"
                info["location"] = settings.CACHES["default"]["LOCATION"]
        except ImportError:
            info["type"] = "local_memory"

        return info


class CacheDecorator:
    """
    缓存装饰器

    用于快速缓存函数结果
    """

    def __init__(self, prefix: str, ttl: int = 900):
        """
        Args:
            prefix: 缓存键前缀
            ttl: 缓存时间（秒）
        """
        self.prefix = prefix
        self.ttl = ttl

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key_parts = [self.prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = ":".join(key_parts)

            # 尝试获取缓存
            cached = cache.get(key)
            if cached is not None:
                return cached

            # 执行函数
            result = func(*args, **kwargs)

            # 设置缓存
            cache.set(key, result, timeout=self.ttl)

            return result

        return wrapper
