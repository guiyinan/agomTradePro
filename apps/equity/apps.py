from django.apps import AppConfig
import logging


class EquityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.equity"
    verbose_name = "个股分析"

    def ready(self):
        """Register equity-owned asset-analysis integrations."""
        logger = logging.getLogger(__name__)
        try:
            from apps.equity.application.repository_provider import (
                get_equity_asset_repository,
                resolve_equity_names,
            )
            from apps.equity.application.services import screen_equity_assets_for_pool
            from core.integration.asset_analysis_market_registry import (
                get_asset_analysis_market_registry,
            )

            registry = get_asset_analysis_market_registry()
            registry.register_asset_repository("equity", get_equity_asset_repository)
            registry.register_pool_screener("equity", screen_equity_assets_for_pool)
            registry.register_name_resolver("equity", resolve_equity_names)
        except Exception as exc:
            logger.error("Failed to register equity market providers: %s", exc)
