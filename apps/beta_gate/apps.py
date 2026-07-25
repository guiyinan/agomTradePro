"""
Beta Gate Django App Configuration
"""

from django.apps import AppConfig


class BetaGateConfig(AppConfig):
    """Beta Gate 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.beta_gate"
    verbose_name = "硬闸门过滤"

    def ready(self) -> None:
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
        # 关键订阅注册失败必须阻止启动，避免风控事件被静默丢弃。
        from .application.subscribers import register_subscribers

        register_subscribers()
