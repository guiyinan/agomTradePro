"""
Task Monitor App Configuration

Django app 配置。
"""

from django.apps import AppConfig


class TaskMonitorConfig(AppConfig):
    """Task Monitor 应用配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.task_monitor"
    verbose_name = "任务监控"

    def ready(self) -> None:
        """应用就绪时的初始化"""
        import logging

        from apps.task_monitor.application.operational_alerts import (
            record_operational_alert,
        )
        from shared.infrastructure.operational_alert_registry import (
            register_operational_alert_handler,
        )

        logger = logging.getLogger(__name__)
        register_operational_alert_handler(record_operational_alert)
        logger.debug("Task Monitor 应用已加载")
