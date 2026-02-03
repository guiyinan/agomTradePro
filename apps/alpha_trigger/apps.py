"""
Alpha Trigger Django App Configuration
"""

from django.apps import AppConfig


class AlphaTriggerConfig(AppConfig):
    """Alpha Trigger 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.alpha_trigger"
    verbose_name = "Alpha 事件触发"

    def ready(self):
        """应用启动时初始化"""
        # 导入信号处理
        try:
            from .application import handlers  # noqa
        except ImportError:
            pass
