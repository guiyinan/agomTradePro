"""
汇率配置服务

从数据库或环境变量读取汇率配置

优先级：cache > DB > env > default(7.0)

⚠️ 默认汇率 7.0 仅用于系统兜底
不用于历史回测的精确分析
"""

import os
from typing import Optional
from datetime import date

from django.core.cache import cache


class ExchangeRateService:
    """汇率服务"""

    @staticmethod
    def get_usd_cny_rate(as_of_date: Optional[date] = None) -> float:
        """
        获取 USD/CNY 汇率

        优先级：
        1. 缓存
        2. 数据库配置
        3. 环境变量
        4. 默认值 7.0

        Args:
            as_of_date: 指定日期的汇率（用于历史数据），None 表示最新汇率

        Returns:
            float: USD/CNY 汇率

        ⚠️ 重要：默认值 7.0 仅用于系统兜底
                  不用于历史回测的精确分析
        """
        # 1. 尝试从缓存获取
        cache_key = f"usd_cny_rate:{as_of_date}" if as_of_date else "usd_cny_rate:latest"
        cached_rate = cache.get(cache_key)
        if cached_rate is not None:
            return float(cached_rate)

        # 2. 尝试从数据库获取（如果实现了汇率表）
        # TODO: 实现 ExchangeRateModel
        # try:
        #     from apps.macro.infrastructure.models import ExchangeRateModel
        #     if as_of_date:
        #         rate = ExchangeRateModel.objects.filter(
        #             from_currency='USD',
        #             to_currency='CNY',
        #             effective_date__lte=as_of_date
        #         ).order_by('-effective_date').first()
        #     else:
        #         rate = ExchangeRateModel.objects.filter(
        #             from_currency='USD',
        #             to_currency='CNY'
        #         ).order_by('-effective_date').first()
        #
        #     if rate:
        #         cache.set(cache_key, rate.rate, 3600)  # 缓存 1 小时
        #         return float(rate.rate)
        # except:
        #     pass

        # 3. 从环境变量获取
        env_rate = os.getenv('USD_CNY_EXCHANGE_RATE')
        if env_rate:
            rate = float(env_rate)
            cache.set(cache_key, rate, 3600)
            return rate

        # 4. 返回默认值
        default_rate = 7.0
        cache.set(cache_key, default_rate, 3600)
        return default_rate

    @staticmethod
    def invalidate_cache():
        """清除汇率缓存"""
        cache.delete_pattern("usd_cny_rate:*")
