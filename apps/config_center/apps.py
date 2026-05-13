from django.apps import AppConfig


class ConfigCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.config_center"
    verbose_name = "配置中心"

    def ready(self):
        from apps.config_center.application.config_summary_service import (
            configure_config_center_summary_repository,
            get_config_center_summary_service,
        )
        from apps.config_center.infrastructure.config_summary_repository import (
            DjangoConfigCenterSummaryRepository,
        )
        from core.integration.runtime_settings import configure_runtime_settings_provider

        configure_config_center_summary_repository(DjangoConfigCenterSummaryRepository())
        configure_runtime_settings_provider(get_config_center_summary_service())

