"""
Realtime Module - Django App Configuration
"""

from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """实时价格监控应用配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    verbose_name = "Realtime Price Monitoring"

    def ready(self):
        """应用启动时的初始化逻辑"""
        # 导入信号处理（如果需要）
        pass
