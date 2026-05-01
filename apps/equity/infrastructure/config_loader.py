"""
Equity Configuration Loader

加载个股筛选相关的配置。
"""

import logging
from decimal import Decimal
from typing import Optional

from django.core.cache import cache

from apps.equity.domain.rules import StockScreeningRule

from .models import StockScreeningRuleConfigModel

logger = logging.getLogger(__name__)


def get_stock_screening_rule(regime: str) -> StockScreeningRule | None:
    """
    获取个股筛选规则（带缓存）

    Args:
        regime: Regime 名称（Recovery/Overheat/Stagflation/Deflation）

    Returns:
        StockScreeningRule 对象或 None（如果未配置）
    """
    cache_key = f"stock_screening_rule:{regime}"
    rule = cache.get(cache_key)

    if rule is None:
        try:
            # 查询最高优先级的启用规则
            config = StockScreeningRuleConfigModel.objects.filter(
                regime=regime,
                is_active=True
            ).order_by('-priority', '-created_at').first()

            if config:
                # 转换为 Domain 层值对象
                rule = StockScreeningRule(
                    regime=config.regime,
                    name=config.rule_name,
                    min_roe=config.min_roe,
                    min_revenue_growth=config.min_revenue_growth,
                    min_profit_growth=config.min_profit_growth,
                    max_debt_ratio=config.max_debt_ratio,
                    max_pe=config.max_pe,
                    max_pb=config.max_pb,
                    min_market_cap=Decimal(config.min_market_cap),
                    sector_preference=config.sector_preference,
                    max_count=config.max_count
                )

                # 缓存 1 小时
                cache.set(cache_key, rule, timeout=3600)
            else:
                logger.warning(f"Stock screening rule not found for regime: {regime}")

        except Exception as e:
            logger.error(f"Error loading stock screening rule for {regime}: {e}")

    return rule
