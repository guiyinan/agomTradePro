"""
基金分析模块 - Django App 配置
"""

import logging

from django.apps import AppConfig


class FundConfig(AppConfig):
    """基金分析模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fund"
    verbose_name = "基金分析模块"

    def ready(self):
        """Register fund-owned asset-analysis integrations."""
        logger = logging.getLogger(__name__)
        try:
            from apps.fund.application.repository_provider import (
                get_fund_asset_repository,
                resolve_fund_holding_names,
                resolve_fund_names,
            )
            from apps.fund.application.services import screen_fund_assets_for_pool
            from shared.infrastructure.asset_analysis_registry import (
                get_asset_analysis_market_registry,
            )

            registry = get_asset_analysis_market_registry()
            registry.register_asset_repository("fund", get_fund_asset_repository)
            registry.register_pool_screener("fund", screen_fund_assets_for_pool)
            registry.register_name_resolver("fund", resolve_fund_names)
            registry.register_name_resolver("fund_holding", resolve_fund_holding_names)
        except Exception as exc:
            logger.error("Failed to register fund market providers: %s", exc)
