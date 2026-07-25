"""
Events Django App Configuration
"""

import logging

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class EventsConfig(AppConfig):
    """Events 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    verbose_name = "事件总线"

    def ready(self) -> None:
        """应用启动时初始化事件总线"""
        try:
            from .application import initialize_event_bus

            initialize_event_bus()
            logger.debug("Event bus initialized successfully")
        except Exception as exc:
            raise ImproperlyConfigured("Failed to initialize the event bus") from exc
