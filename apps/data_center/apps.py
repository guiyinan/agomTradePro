"""Data Center App Configuration."""

from django.apps import AppConfig


class DataCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.data_center"
    verbose_name = "Data Center"

    def ready(self) -> None:
        import apps.data_center.interface.admin  # noqa: F401
        from apps.data_center.application.config_summary_service import (
            configure_data_center_config_summary_repository,
        )
        from apps.data_center.infrastructure.config_summary_repository import (
            DjangoDataCenterConfigSummaryRepository,
        )

        configure_data_center_config_summary_repository(DjangoDataCenterConfigSummaryRepository())
        # Registry is lazily initialised on first request via get_registry().
        # Do NOT query the DB here — AppConfig.ready() runs before migrations
        # complete, which would raise RuntimeWarning and break fresh setups.
