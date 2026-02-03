"""
Events Django App Configuration
"""

from django.apps import AppConfig


class EventsConfig(AppConfig):
    """Events 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    verbose_name = "事件总线"

    def ready(self):
        """应用启动时初始化事件总线"""
        # 初始化全局事件总线
        try:
            from .application import initialize_event_bus  # noqa
        except ImportError:
            pass
