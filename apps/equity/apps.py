import logging

from django.apps import AppConfig


class EquityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.equity"
    verbose_name = "个股分析"

    def ready(self) -> None:
        """Register equity-owned asset-analysis integrations."""
        logger = logging.getLogger(__name__)
        try:
            from apps.equity.application.account_gateway import register_equity_account_gateway
            from apps.equity.application.repository_provider import (
                get_equity_asset_repository,
                resolve_equity_names,
            )
            from apps.equity.application.sector_market_gateway import (
                register_sector_market_gateway,
            )
            from apps.equity.application.services import screen_equity_assets_for_pool
            from core.integration.asset_analysis_market_registry import (
                get_asset_analysis_market_registry,
            )

            registry = get_asset_analysis_market_registry()
            registry.register_asset_repository("equity", get_equity_asset_repository)
            registry.register_pool_screener("equity", screen_equity_assets_for_pool)
            registry.register_name_resolver("equity", resolve_equity_names)
            register_equity_account_gateway()
            register_sector_market_gateway()
        except Exception as exc:
            logger.error(
                "Failed to register equity market providers error_type=%s",
                type(exc).__name__,
            )
