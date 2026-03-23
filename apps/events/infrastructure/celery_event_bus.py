"""
Celery Event Bus

使用 Celery 实现真正异步事件发布的事件总线。
继承 InMemoryEventBus，仅覆写 publish_async 方法。
"""

import logging
from typing import Optional

from ..domain.entities import DomainEvent, EventBusConfig
from ..domain.services import InMemoryEventBus

logger = logging.getLogger(__name__)


class CeleryEventBus(InMemoryEventBus):
    """
    基于 Celery 的事件总线

    同步发布使用父类 InMemoryEventBus 的实现，
    异步发布通过 Celery task 执行。
    """

    def publish_async(self, event: DomainEvent) -> None:
        """
        异步发布事件（通过 Celery）

        Args:
            event: 领域事件
        """
        try:
            from ..application.tasks import publish_event_async

            publish_event_async.delay(
                event_type=event.event_type.value,
                payload=event.payload,
                metadata=event.metadata,
                event_id=event.event_id,
                occurred_at=event.occurred_at.isoformat() if event.occurred_at else None,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
            )
            logger.debug(f"Event queued for async publish: {event.event_id}")

        except Exception as exc:
            logger.warning(
                f"Celery async publish failed, falling back to sync: {exc}"
            )
            # 降级为同步发布
            self.publish(event)


def is_celery_available() -> bool:
    """检查 Celery 是否可用"""
    try:
        from celery import current_app
        # 检查 broker 是否配置
        return bool(current_app.conf.broker_url)
    except Exception:
        return False
