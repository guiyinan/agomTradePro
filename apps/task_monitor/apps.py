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

    def ready(self):
        """应用就绪时的初始化"""
        import logging

        logger = logging.getLogger(__name__)
        logger.info("Task Monitor 应用已加载")
