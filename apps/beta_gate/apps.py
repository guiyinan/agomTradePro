"""
Beta Gate Django App Configuration
"""

from django.apps import AppConfig


class BetaGateConfig(AppConfig):
    """Beta Gate 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.beta_gate"
    verbose_name = "硬闸门过滤"

    def ready(self):
        """应用启动时初始化"""
        # 导入信号处理
        try:
            from .application import handlers  # noqa
        except ImportError:
            pass
