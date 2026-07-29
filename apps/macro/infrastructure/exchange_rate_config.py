"""
汇率配置服务

从数据库或环境变量读取汇率配置

优先级：cache > DB > env；全部缺失时失败关闭。
"""

import logging
import math
import os
from datetime import date
from typing import Any

from django.core.cache import cache

logger = logging.getLogger(__name__)


def _validated_rate(value: Any) -> float:
    """Return a finite positive FX rate from a dynamic storage boundary."""

    if isinstance(value, bool):
        raise ValueError("usd_cny_exchange_rate_invalid")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("usd_cny_exchange_rate_invalid") from exc
    if not math.isfinite(rate) or rate <= 0 or rate > 1_000:
        raise ValueError("usd_cny_exchange_rate_invalid")
    return rate


class ExchangeRateService:
    """汇率服务"""

    @staticmethod
    def get_usd_cny_rate(as_of_date: date | None = None) -> float:
        """
        获取 USD/CNY 汇率

        优先级：
        1. 缓存
        2. 数据库配置
        3. 环境变量

        Args:
            as_of_date: 指定日期的汇率（用于历史数据），None 表示最新汇率

        Returns:
            float: USD/CNY 汇率

        缺失或非法汇率不会使用静态金融默认值。
        """
        # 1. 尝试从缓存获取
        cache_key = f"usd_cny_rate:{as_of_date}" if as_of_date else "usd_cny_rate:latest"
        cached_rate = cache.get(cache_key)
        if cached_rate is not None:
            return _validated_rate(cached_rate)

        # 2. 尝试从数据库获取
        try:
            from apps.macro.infrastructure.models import ExchangeRateModel

            if as_of_date:
                rate_obj = (
                    ExchangeRateModel._default_manager.filter(
                        from_currency="USD",
                        to_currency="CNY",
                        effective_date__lte=as_of_date,
                    )
                    .order_by("-effective_date")
                    .first()
                )
            else:
                rate_obj = (
                    ExchangeRateModel._default_manager.filter(
                        from_currency="USD", to_currency="CNY"
                    )
                    .order_by("-effective_date")
                    .first()
                )

            if rate_obj:
                rate = _validated_rate(rate_obj.rate)
                cache.set(cache_key, rate, 3600)  # 缓存 1 小时
                return rate
        except Exception as exc:
            logger.warning("Exchange-rate database lookup failed: %s", type(exc).__name__)

        # 3. 从环境变量获取
        env_rate = os.getenv("USD_CNY_EXCHANGE_RATE")
        if env_rate:
            rate = _validated_rate(env_rate)
            cache.set(cache_key, rate, 3600)
            return rate

        raise RuntimeError("usd_cny_exchange_rate_unavailable")

    @staticmethod
    def invalidate_cache() -> None:
        """清除汇率缓存"""
        delete_pattern = getattr(cache, "delete_pattern", None)
        if callable(delete_pattern):
            delete_pattern("usd_cny_rate:*")
            return
        cache.delete("usd_cny_rate:latest")
