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
        from .application.config_summary_service import (
            configure_beta_gate_config_summary_repository,
        )
        from .infrastructure.config_summary_repository import (
            DjangoBetaGateConfigSummaryRepository,
        )

        configure_beta_gate_config_summary_repository(
            DjangoBetaGateConfigSummaryRepository()
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
