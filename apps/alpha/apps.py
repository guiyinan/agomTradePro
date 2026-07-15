"""
Alpha App Configuration

Django app 配置。
"""

from django.apps import AppConfig


class AlphaConfig(AppConfig):
    """Alpha 应用配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.alpha"
    verbose_name = "Alpha 信号抽象层"

    def ready(self):
        """应用就绪时的初始化"""
        import logging

        from apps.alpha.application.data_center_gateway import (
            register_alpha_data_center_runtime,
        )
        from core.integration.unified_signal_registry import register_alpha_score_fetcher

        register_alpha_data_center_runtime()

        def fetch_stock_scores(**kwargs):
            from apps.alpha.application.services import AlphaService

            return AlphaService().get_stock_scores(**kwargs)

        register_alpha_score_fetcher(fetch_stock_scores)

        logger = logging.getLogger(__name__)
        logger.debug("Alpha 应用已加载")
