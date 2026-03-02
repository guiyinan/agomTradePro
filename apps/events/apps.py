"""
Events Django App Configuration
"""

import logging

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class EventsConfig(AppConfig):
    """Events 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    verbose_name = "事件总线"

    def ready(self):
        """应用启动时初始化事件总线"""
        # P1-10: 实际调用初始化函数（而不仅仅是导入）
        try:
            from .application import initialize_event_bus
            # 执行初始化
            initialize_event_bus()
            logger.info("Event bus initialized successfully")
        except ImportError as e:
            logger.warning(f"Could not import initialize_event_bus: {e}")
        except Exception as e:
            logger.error(f"Failed to initialize event bus: {e}", exc_info=True)
