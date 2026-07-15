from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    verbose_name = "仪表盘"

    def ready(self) -> None:
        """Register Dashboard-owned integration providers."""

        from apps.dashboard.application.data_center_gateway import (
            register_dashboard_data_center_runtime,
        )

        register_dashboard_data_center_runtime()
