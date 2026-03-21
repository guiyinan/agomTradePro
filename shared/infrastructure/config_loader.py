"""
Configuration Loader for AgomTradePro

提供带缓存的配置访问接口，替代硬编码。
"""

import os
import logging
from typing import Optional, Dict, List, Any

from django.core.cache import cache
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


# 默认硬编码配置（fallback）
DEFAULT_ASSET_TICKERS = {
    "a_share_growth": "000300.SH",  # 沪深300
    "a_share_value": "000905.SH",   # 中证500
    "china_bond": "H11025.CSI",     # 中债总财富指数
    "gold": "AU9999.SGE",           # 上海黄金
    "commodity": "NH0100.NHF",      # 南华商品指数
    "cash": None,
}

DEFAULT_INDICATOR_THRESHOLDS = {
    'CN_PMI': {'bullish': 50, 'bearish': 50},
    'CN_CPI': {'bullish': 2.0, 'bearish': 3.0},
}


def _legacy_fallback_allowed() -> bool:
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    return bool(
        getattr(settings, "DEBUG", False)
        or "test" in settings_module
        or "development" in settings_module
        or getattr(settings, "ALLOW_LEGACY_CONFIG_FALLBACK", False)
    )


def get_asset_ticker(asset_class: str) -> Optional[str]:
    """
    获取资产代码（带缓存）

    Args:
        asset_class: 资产类别代码

    Returns:
        交易代码，如不存在则返回 None
    """
    from .models import AssetConfigModel

    cache_key = f"asset_ticker:{asset_class}"
    ticker = cache.get(cache_key)

    if ticker is None:
        try:
            config = AssetConfigModel.objects.filter(
                asset_class=asset_class,
                is_active=True
            ).first()

            if config:
                ticker = config.ticker_symbol
                cache.set(cache_key, ticker, timeout=3600)  # 缓存 1 小时
            else:
                if _legacy_fallback_allowed():
                    ticker = DEFAULT_ASSET_TICKERS.get(asset_class)
                    logger.warning(
                        "Asset config not found for %s, using legacy fallback: %s",
                        asset_class,
                        ticker,
                    )
                else:
                    logger.error("Asset config not found for %s and legacy fallback is disabled", asset_class)
                    ticker = None

        except Exception as e:
            logger.error(f"Error loading asset ticker for {asset_class}: {e}")
            ticker = DEFAULT_ASSET_TICKERS.get(asset_class) if _legacy_fallback_allowed() else None

    return ticker


def get_indicator_config(code: str) -> Optional[Dict[str, Any]]:
    """
    获取指标配置（带缓存）

    Args:
        code: 指标代码

    Returns:
        配置字典，如不存在则返回 None
    """
    from .models import IndicatorConfigModel

    cache_key = f"indicator_config:{code}"
    config = cache.get(cache_key)

    if config is None:
        try:
            obj = IndicatorConfigModel.objects.filter(
                code=code,
                is_active=True
            ).first()

            if obj:
                config = {
                    'code': obj.code,
                    'name': obj.name,
                    'category': obj.category,
                    'unit': obj.unit,
                    'threshold_bullish': obj.threshold_bullish,
                    'threshold_bearish': obj.threshold_bearish,
                    'data_source': obj.data_source,
                    'fetch_frequency': obj.fetch_frequency,
                    'publication_lag_days': obj.publication_lag_days,
                }
                cache.set(cache_key, config, timeout=3600)
            else:
                if _legacy_fallback_allowed():
                    defaults = DEFAULT_INDICATOR_THRESHOLDS.get(code, {})
                    config = {
                        'code': code,
                        'threshold_bullish': defaults.get('bullish'),
                        'threshold_bearish': defaults.get('bearish'),
                    }
                    logger.warning("Indicator config not found for %s, using legacy fallback", code)
                else:
                    logger.error("Indicator config not found for %s and legacy fallback is disabled", code)
                    config = None

        except Exception as e:
            logger.error(f"Error loading indicator config for {code}: {e}")
            config = None

    return config


def get_eligibility_config(asset_class: str, regime: str) -> Optional[str]:
    """
    获取准入配置（带缓存）

    Args:
        asset_class: 资产类别
        regime: Regime 名称

    Returns:
        准入状态 (preferred/neutral/hostile)，如不存在则返回 None
    """
    from .models import RegimeEligibilityConfigModel

    cache_key = f"eligibility:{asset_class}:{regime}"
    eligibility = cache.get(cache_key)

    if eligibility is None:
        try:
            obj = RegimeEligibilityConfigModel.objects.filter(
                asset_class=asset_class,
                regime=regime,
                is_active=True
            ).first()

            if obj:
                eligibility = obj.eligibility
                cache.set(cache_key, eligibility, timeout=3600)
            else:
                logger.warning(f"Eligibility config not found for {asset_class}@{regime}")

        except Exception as e:
            logger.error(f"Error loading eligibility for {asset_class}@{regime}: {e}")

    return eligibility


def get_risk_parameter(
    key: str,
    policy_level: Optional[str] = None,
    regime: Optional[str] = None,
    asset_class: Optional[str] = None
) -> Optional[Any]:
    """
    获取风险参数（带缓存）

    Args:
        key: 参数键
        policy_level: 政策档位（可选）
        regime: Regime（可选）
        asset_class: 资产类别（可选）

    Returns:
        参数值，如不存在则返回 None
    """
    from .models import RiskParameterConfigModel

    cache_key = f"risk_param:{key}:{policy_level or 'all'}:{regime or 'all'}:{asset_class or 'all'}"
    value = cache.get(cache_key)

    if value is None:
        try:
            queryset = RiskParameterConfigModel.objects.filter(
                key=key,
                is_active=True
            )

            # 应用过滤条件
            if policy_level:
                queryset = queryset.filter(
                    models.Q(policy_level='') | models.Q(policy_level=policy_level)
                )
            if regime:
                queryset = queryset.filter(
                    models.Q(regime='') | models.Q(regime=regime)
                )
            if asset_class:
                queryset = queryset.filter(
                    models.Q(asset_class='') | models.Q(asset_class=asset_class)
                )

            obj = queryset.first()

            if obj:
                value = obj.get_value()
                cache.set(cache_key, value, timeout=3600)
            else:
                logger.warning(f"Risk parameter not found: {key}")

        except Exception as e:
            logger.error(f"Error loading risk parameter {key}: {e}")

    return value


def invalidate_config_cache(pattern: str = None):
    """
    清除配置缓存

    Args:
        pattern: 缓存键模式（可选），None 表示清除所有配置缓存
    """
    if pattern:
        # 清除特定模式的缓存
        # 注意：Django 的 cache 不支持模式匹配，这里需要手动处理
        # 简化版本：只清除特定键
        cache.delete(pattern)
    else:
        # 清除所有配置缓存（需要遍历所有配置键）
        # 在生产环境中，可以使用专门的缓存管理工具
        pass


def get_all_asset_configs() -> List[Dict[str, Any]]:
    """
    获取所有资产配置

    Returns:
        资产配置列表
    """
    from .models import AssetConfigModel

    try:
        configs = AssetConfigModel.objects.filter(is_active=True)
        return [
            {
                'asset_class': c.asset_class,
                'display_name': c.display_name,
                'ticker_symbol': c.ticker_symbol,
                'data_source': c.data_source,
                'category': c.category,
            }
            for c in configs
        ]
    except Exception as e:
        logger.error(f"Error loading all asset configs: {e}")
        return []


def get_all_indicator_configs() -> List[Dict[str, Any]]:
    """
    获取所有指标配置

    Returns:
        指标配置列表
    """
    from .models import IndicatorConfigModel

    try:
        configs = IndicatorConfigModel.objects.filter(is_active=True)
        return [
            {
                'code': c.code,
                'name': c.name,
                'category': c.category,
                'unit': c.unit,
                'threshold_bullish': c.threshold_bullish,
                'threshold_bearish': c.threshold_bearish,
            }
            for c in configs
        ]
    except Exception as e:
        logger.error(f"Error loading all indicator configs: {e}")
        return []


def get_sector_weights(regime: str) -> Dict[str, float]:
    """
    获取板块权重配置（带缓存）

    Args:
        regime: Regime 名称

    Returns:
        {板块名称: 权重}
    """
    from .models import SectorPreferenceConfigModel

    cache_key = f"sector_weights:{regime}"
    weights = cache.get(cache_key)

    if weights is None:
        try:
            configs = SectorPreferenceConfigModel.objects.filter(
                regime=regime,
                is_active=True
            )

            weights = {
                config.sector_name: config.weight
                for config in configs
            }

            # 缓存 1 小时
            cache.set(cache_key, weights, timeout=3600)

        except Exception as e:
            logger.error(f"Error loading sector weights for {regime}: {e}")
            weights = {}

    return weights


def get_fund_type_preferences(regime: str) -> List[str]:
    """
    获取基金类型偏好（带缓存）

    Args:
        regime: Regime 名称

    Returns:
        偏好的基金类型列表
    """
    from .models import FundTypePreferenceConfigModel

    cache_key = f"fund_type_preferences:{regime}"
    types = cache.get(cache_key)

    if types is None:
        try:
            configs = FundTypePreferenceConfigModel.objects.filter(
                regime=regime,
                is_active=True
            ).order_by('-priority')

            types = [config.fund_type for config in configs]

            # 缓存 1 小时
            cache.set(cache_key, types, timeout=3600)

        except Exception as e:
            logger.error(f"Error loading fund type preferences for {regime}: {e}")
            types = []

    return types
