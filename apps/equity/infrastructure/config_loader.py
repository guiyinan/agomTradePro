"""
Equity Configuration Loader

加载个股筛选相关的配置。
"""

import logging
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import DatabaseError

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
    cached_rule = cache.get(cache_key)
    if isinstance(cached_rule, StockScreeningRule):
        return cached_rule
    if cached_rule is not None:
        cache.delete(cache_key)

    try:
        config = (
            StockScreeningRuleConfigModel._default_manager.filter(
                regime=regime,
                is_active=True,
            )
            .order_by("-priority", "-created_at")
            .first()
        )
        if config is None:
            logger.warning("Stock screening rule not found for requested regime")
            return None

        raw_sector_preference = config.sector_preference
        sector_preference = (
            list(raw_sector_preference)
            if isinstance(raw_sector_preference, list)
            and all(isinstance(item, str) for item in raw_sector_preference)
            else None
        )
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
            sector_preference=sector_preference,
            max_count=config.max_count,
        )
        cache.set(cache_key, rule, timeout=3600)
        return rule
    except (DatabaseError, InvalidOperation, ValueError, TypeError) as exc:
        logger.error(
            "Error loading stock screening rule error_type=%s",
            type(exc).__name__,
        )
        return None
