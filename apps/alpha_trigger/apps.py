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
        from .application.global_alert_service import (
            configure_alpha_trigger_global_alert_repository,
        )
        from .infrastructure.global_alert_repository import (
            DjangoAlphaTriggerGlobalAlertRepository,
        )

        configure_alpha_trigger_global_alert_repository(
            DjangoAlphaTriggerGlobalAlertRepository()
        )

        # 导入admin以注册模型
        try:
            from .interface import admin  # noqa
        except ImportError:
            pass
        # 导入信号处理
        try:
            from .application import handlers  # noqa
        except ImportError:
            pass
        # 注册事件订阅器（通过 registry 实现反向依赖）
        try:
            from .application.subscribers import register_subscribers
            register_subscribers()
        except ImportError as e:
            import logging
            logging.getLogger(__name__).warning(f"Could not import subscribers: {e}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to register subscribers: {e}")
