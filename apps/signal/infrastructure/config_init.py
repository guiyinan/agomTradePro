"""
Configuration Initialization for Domain Layer

在应用启动时将数据库配置注入到 Domain 层。
"""

from typing import Dict

from apps.signal.domain import rules as signal_rules
from apps.signal.domain.entities import Eligibility
from shared.infrastructure.models import RegimeEligibilityConfigModel


def _load_eligibility_matrix_from_db() -> dict[str, dict[str, Eligibility]]:
    """从数据库加载准入矩阵"""
    matrix = {}

    configs = RegimeEligibilityConfigModel.objects.filter(is_active=True)

    for config in configs:
        if config.asset_class not in matrix:
            matrix[config.asset_class] = {}

        matrix[config.asset_class][config.regime] = Eligibility(config.eligibility)

    return matrix


def initialize_domain_config():
    """
    初始化 Domain 层配置

    从数据库加载配置并注入到 Domain 层。
    应在 Django 应用启动时调用（例如 apps.py 的 ready() 方法）。
    """
    # 设置准入矩阵提供者
    signal_rules.set_eligibility_matrix_provider(_load_eligibility_matrix_from_db)


def refresh_domain_config():
    """
    刷新 Domain 层配置

    当配置表更新后调用，强制重新加载配置。
    """
    # 清除缓存（如果有的话）
    from django.core.cache import cache
    cache.delete_pattern('eligibility:*')

    # 重新注入配置
    initialize_domain_config()
