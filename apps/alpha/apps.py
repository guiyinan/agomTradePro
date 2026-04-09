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

        logger = logging.getLogger(__name__)
        logger.debug("Alpha 应用已加载")
