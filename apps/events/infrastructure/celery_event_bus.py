"""
Celery Event Bus

使用 Celery 实现真正异步事件发布的事件总线。
继承 InMemoryEventBus，仅覆写 publish_async 方法。
"""

import logging
from typing import Any, Protocol, cast

from ..domain.entities import DomainEvent
from ..domain.services import InMemoryEventBus

logger = logging.getLogger(__name__)


class _PublishEventTaskProtocol(Protocol):
    def delay(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
        event_id: str,
        occurred_at: str,
        correlation_id: str | None,
        causation_id: str | None,
    ) -> object: ...


def _optional_metadata_string(event: DomainEvent, key: str) -> str | None:
    value = event.get_metadata_value(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


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

            task = cast(_PublishEventTaskProtocol, publish_event_async)
            task.delay(
                event_type=event.event_type.value,
                payload=event.payload,
                metadata=event.metadata,
                event_id=event.event_id,
                occurred_at=event.occurred_at.isoformat(),
                correlation_id=_optional_metadata_string(event, "correlation_id"),
                causation_id=_optional_metadata_string(event, "causation_id"),
            )
            logger.debug(f"Event queued for async publish: {event.event_id}")

        except Exception as exc:
            logger.warning("Celery async publish failed, falling back to sync: %s", exc)
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
