"""
Realtime Module - Django App Configuration
"""

from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """实时价格监控应用配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    verbose_name = "Realtime Price Monitoring"

    def ready(self) -> None:
        """应用启动时的初始化逻辑"""
        from apps.realtime.application.data_center_gateway import (
            register_realtime_data_center_runtime,
        )
        from apps.realtime.application.repository_provider import (
            get_realtime_price_repository,
        )
        from core.integration.policy_hedging_registry import (
            register_price_repository_factory,
        )

        register_realtime_data_center_runtime()
        register_price_repository_factory(get_realtime_price_repository)
