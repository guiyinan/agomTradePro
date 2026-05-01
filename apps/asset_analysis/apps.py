"""
Asset Analysis App Configuration
"""

import logging

from django.apps import AppConfig


class AssetAnalysisConfig(AppConfig):
    """资产分析应用配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.asset_analysis"
    verbose_name = "通用资产分析"

    def ready(self):
        """Register asset-analysis-owned integration providers."""
        logger = logging.getLogger(__name__)
        try:
            from apps.asset_analysis.application.repository_provider import (
                resolve_index_asset_names,
            )
            from core.integration.asset_analysis_market_registry import (
                get_asset_analysis_market_registry,
            )

            registry = get_asset_analysis_market_registry()
            registry.register_name_resolver("index", resolve_index_asset_names)
        except Exception as exc:
            logger.error("Failed to register asset_analysis market providers: %s", exc)
