"""
Alpha Trigger Django App Configuration
"""

from django.apps import AppConfig


class AlphaTriggerConfig(AppConfig):
    """Alpha Trigger 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.alpha_trigger"
    verbose_name = "Alpha 事件触发"

    def ready(self) -> None:
        """应用启动时初始化"""
        from core.integration.alpha_candidate_registry import (
            register_alpha_candidate_repository_factory,
        )

        from . import checks as _checks  # noqa: F401
        from .application.repository_provider import get_alpha_candidate_repository

        register_alpha_candidate_repository_factory(get_alpha_candidate_repository)

        from .application.global_alert_service import (
            configure_alpha_trigger_global_alert_repository,
        )
        from .infrastructure.global_alert_repository import (
            DjangoAlphaTriggerGlobalAlertRepository,
        )

        configure_alpha_trigger_global_alert_repository(DjangoAlphaTriggerGlobalAlertRepository())

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
        # 关键订阅注册失败必须阻止启动，避免 Alpha 事件被静默丢弃。
        from .application.subscribers import register_subscribers

        register_subscribers()
