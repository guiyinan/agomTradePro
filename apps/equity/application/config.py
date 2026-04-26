"""
估值修复配置工厂

从 Django settings 或数据库构建 Domain 层配置对象。
遵循四层架构规范：
- Application 层可以访问 Django settings 和数据库
- Domain 层保持纯净（无 Django 依赖）

配置优先级：
1. 数据库激活配置（ValuationRepairConfigModel.is_active=True）
2. Django settings 中的 EQUITY_VALUATION_* 配置
3. ValuationRepairConfig 的默认值
"""

import logging
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache

from apps.equity.domain.entities_valuation_repair import ValuationRepairConfig

logger = logging.getLogger(__name__)

# 缓存 Key
_CONFIG_CACHE_KEY = "equity:valuation_repair_config"
_CONFIG_CACHE_TIMEOUT = 300  # 5 分钟缓存


# Settings 配置名到实体字段的映射
_SETTINGS_MAPPING = {
    # 历史数据要求
    'EQUITY_VALUATION_MIN_HISTORY_POINTS': 'min_history_points',
    'EQUITY_VALUATION_DEFAULT_LOOKBACK_DAYS': 'default_lookback_days',

    # 修复确认参数
    'EQUITY_VALUATION_CONFIRM_WINDOW': 'confirm_window',
    'EQUITY_VALUATION_MIN_REBOUND': 'min_rebound',

    # 停滞检测参数
    'EQUITY_VALUATION_STALL_WINDOW': 'stall_window',
    'EQUITY_VALUATION_STALL_MIN_PROGRESS': 'stall_min_progress',

    # 阶段判定阈值
    'EQUITY_VALUATION_TARGET_PERCENTILE': 'target_percentile',
    'EQUITY_VALUATION_UNDERVALUED_THRESHOLD': 'undervalued_threshold',
    'EQUITY_VALUATION_NEAR_TARGET_THRESHOLD': 'near_target_threshold',
    'EQUITY_VALUATION_OVERVALUED_THRESHOLD': 'overvalued_threshold',

    # 复合百分位权重
    'EQUITY_VALUATION_PE_WEIGHT': 'pe_weight',
    'EQUITY_VALUATION_PB_WEIGHT': 'pb_weight',

    # 置信度计算参数
    'EQUITY_VALUATION_CONFIDENCE_BASE': 'confidence_base',
    'EQUITY_VALUATION_CONFIDENCE_SAMPLE_THRESHOLD': 'confidence_sample_threshold',
    'EQUITY_VALUATION_CONFIDENCE_SAMPLE_BONUS': 'confidence_sample_bonus',
    'EQUITY_VALUATION_CONFIDENCE_BLEND_BONUS': 'confidence_blend_bonus',
    'EQUITY_VALUATION_CONFIDENCE_REPAIR_START_BONUS': 'confidence_repair_start_bonus',
    'EQUITY_VALUATION_CONFIDENCE_NOT_STALLED_BONUS': 'confidence_not_stalled_bonus',

    # 其他阈值
    'EQUITY_VALUATION_REPAIRING_THRESHOLD': 'repairing_threshold',
    'EQUITY_VALUATION_ETA_MAX_DAYS': 'eta_max_days',
}


def _get_config_from_db() -> ValuationRepairConfig | None:
    """从数据库获取激活的配置"""
    try:
        from apps.equity.infrastructure.providers import ValuationRepairConfigRepository

        db_config = ValuationRepairConfigRepository().get_active_domain_config()
        if db_config:
            logger.debug("Using active DB valuation repair config")
            return db_config
    except Exception as e:
        logger.warning(f"Failed to get config from DB: {e}")
    return None


def _get_config_from_settings() -> ValuationRepairConfig:
    """从 settings 构建估值修复配置"""
    config_kwargs = {}

    for settings_name, field_name in _SETTINGS_MAPPING.items():
        if hasattr(settings, settings_name):
            config_kwargs[field_name] = getattr(settings, settings_name)

    return ValuationRepairConfig(**config_kwargs)


def get_valuation_repair_config(use_cache: bool = True) -> ValuationRepairConfig:
    """获取估值修复配置

    优先级：
    1. 缓存（如果 use_cache=True）
    2. 数据库激活配置
    3. Django settings 配置
    4. ValuationRepairConfig 默认值

    Args:
        use_cache: 是否使用缓存（默认 True）

    Returns:
        ValuationRepairConfig 实例
    """
    # 1. 尝试从缓存获取
    if use_cache:
        cached = cache.get(_CONFIG_CACHE_KEY)
        if cached is not None:
            return cached

    # 2. 尝试从数据库获取
    db_config = _get_config_from_db()
    if db_config:
        if use_cache:
            cache.set(_CONFIG_CACHE_KEY, db_config, _CONFIG_CACHE_TIMEOUT)
        return db_config

    # 3. 从 settings 构建
    settings_config = _get_config_from_settings()
    if use_cache:
        cache.set(_CONFIG_CACHE_KEY, settings_config, _CONFIG_CACHE_TIMEOUT)

    return settings_config


def get_valuation_repair_config_summary(use_cache: bool = True) -> dict[str, Any]:
    """获取用于页面展示的估值修复配置摘要。"""
    from apps.equity.domain.entities_valuation_repair import DEFAULT_VALUATION_REPAIR_CONFIG

    runtime_config = get_valuation_repair_config(use_cache=use_cache)
    active_version = 0
    source = "settings"

    try:
        from apps.equity.infrastructure.providers import ValuationRepairConfigRepository

        active_version = ValuationRepairConfigRepository().get_active_version()
        if active_version:
            source = "database"
    except Exception as e:
        logger.warning(f"Failed to get config summary from DB: {e}")

    if active_version == 0 and runtime_config == DEFAULT_VALUATION_REPAIR_CONFIG:
        source = "default"

    return {
        "version": active_version,
        "source": source,
        "target_percentile": runtime_config.target_percentile,
        "undervalued_threshold": runtime_config.undervalued_threshold,
        "near_target_threshold": runtime_config.near_target_threshold,
        "overvalued_threshold": runtime_config.overvalued_threshold,
        "confirm_window": runtime_config.confirm_window,
        "stall_window": runtime_config.stall_window,
        "min_rebound": runtime_config.min_rebound,
        "repairing_threshold": runtime_config.repairing_threshold,
    }


def clear_config_cache():
    """清除配置缓存

    在更新配置后调用，确保下次请求获取最新配置。
    """
    cache.delete(_CONFIG_CACHE_KEY)
    logger.info("Valuation repair config cache cleared")


# 向后兼容的别名
get_cached_valuation_repair_config = get_valuation_repair_config
