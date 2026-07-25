"""
Events Application Tasks

事件 Celery 异步任务定义。
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any, ParamSpec, Protocol, TypeVar, cast

from celery import shared_task
from celery.utils.log import get_task_logger
from django.utils import timezone

from ..domain.entities import (
    DomainEvent,
    EventHandler,
    EventType,
    create_event,
)
from ..domain.services import get_event_bus
from .repository_provider import (
    get_event_store,
    get_replay_handler,
    get_snapshot_store,
)

logger = get_task_logger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class _SharedTaskFactoryProtocol(Protocol):
    def __call__(
        self,
        *,
        name: str,
        bind: bool,
        max_retries: int,
        default_retry_delay: int,
        time_limit: int,
        soft_time_limit: int,
    ) -> object: ...


_shared_task_factory = cast(_SharedTaskFactoryProtocol, shared_task)


def _celery_task(
    *,
    name: str,
    max_retries: int,
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Provide a typed boundary around Celery's runtime task decorator."""
    decorator = _shared_task_factory(
        name=name,
        bind=True,
        max_retries=max_retries,
        default_retry_delay=60,
        time_limit=300,
        soft_time_limit=280,
    )
    return cast(Callable[[Callable[_P, _R]], Callable[_P, _R]], decorator)


class _TaskRequestProtocol(Protocol):
    retries: int


class _BoundTaskProtocol(Protocol):
    request: _TaskRequestProtocol
    max_retries: int

    def retry(self, *, exc: BaseException) -> BaseException: ...


class _PublishEventStoreProtocol(Protocol):
    def get_by_id(self, event_id: str) -> DomainEvent | None: ...

    def append(self, event: DomainEvent) -> bool: ...


def _parse_optional_timestamp(value: str | None, *, field_name: str) -> datetime | None:
    """Parse an explicitly timezone-aware ISO timestamp."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO datetime") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed


def _persist_event_for_delivery(
    event_store: _PublishEventStoreProtocol,
    event: DomainEvent,
    *,
    occurred_at_was_generated: bool,
) -> None:
    """Persist once and permit a retry to resume delivery of the same event."""
    existing = event_store.get_by_id(event.event_id)
    if existing is not None:
        same_event = (
            existing.event_id == event.event_id
            and existing.event_type == event.event_type
            and existing.payload == event.payload
            and existing.metadata == event.metadata
            and existing.version == event.version
            and (occurred_at_was_generated or existing.occurred_at == event.occurred_at)
        )
        if not same_event:
            raise ValueError(f"event_id conflicts with a different event: {event.event_id}")
        return
    if not event_store.append(event):
        raise RuntimeError(f"Event persistence failed; event was not published: {event.event_id}")


def _failure_result(
    exc: BaseException,
    **context: object,
) -> dict[str, Any]:
    return {
        "success": False,
        **context,
        "error": str(exc),
    }


def _retry_or_failure(
    task: _BoundTaskProtocol,
    exc: BaseException,
    **context: object,
) -> dict[str, Any]:
    if task.request.retries < task.max_retries:
        raise task.retry(exc=exc)
    return _failure_result(exc, retries=task.request.retries, **context)


# ========== 异步事件发布 ==========


@_celery_task(
    name="events.publish_event_async",
    max_retries=3,
)
def publish_event_async(
    self: _BoundTaskProtocol,
    event_type: str,
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    occurred_at: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> dict[str, Any]:
    """
    异步发布事件

    Args:
        self: Celery 任务实例
        event_type: 事件类型
        payload: 事件负载
        metadata: 事件元数据
        event_id: 事件 ID
        occurred_at: 发生时间（ISO 格式）
        correlation_id: 关联 ID
        causation_id: 因果 ID

    Returns:
        执行结果
    """
    try:
        event = create_event(
            event_type=EventType(event_type),
            payload=payload,
            metadata=metadata or {},
            event_id=event_id,
            occurred_at=_parse_optional_timestamp(
                occurred_at,
                field_name="occurred_at",
            ),
        )

        # 添加关联 ID
        if correlation_id:
            event = event.with_correlation_id(correlation_id)
        if causation_id:
            event = event.with_causation_id(causation_id)

        # 获取事件总线和存储
        event_bus = get_event_bus()
        event_store = get_event_store()

        _persist_event_for_delivery(
            event_store,
            event,
            occurred_at_was_generated=occurred_at is None,
        )

        # 发布事件
        event_bus.publish(event)

        logger.info(f"Event published async: {event.event_id} ({event_type})")

        return {
            "success": True,
            "event_id": event.event_id,
            "event_type": event_type,
            "published_at": timezone.now().isoformat(),
        }

    except (TypeError, ValueError) as exc:
        logger.warning("Rejected invalid event task input: %s", exc)
        return _failure_result(exc, event_type=event_type)
    except Exception as exc:
        logger.error(f"Failed to publish event async: {exc}", exc_info=True)
        return _retry_or_failure(self, exc, event_type=event_type)


@_celery_task(
    name="events.publish_batch_events_async",
    max_retries=3,
)
def publish_batch_events_async(
    self: _BoundTaskProtocol,
    events_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    批量异步发布事件

    Args:
        self: Celery 任务实例
        events_data: 事件数据列表，每个事件包含：
            - event_type: 事件类型
            - payload: 事件负载
            - metadata: 事件元数据（可选）
            - event_id: 事件 ID（可选）

    Returns:
        执行结果
    """
    success_count = 0
    failed_count = 0
    errors: list[dict[str, object]] = []

    try:
        event_bus = get_event_bus()
        event_store = get_event_store()
    except Exception as exc:
        logger.error("Failed to initialize batch event publication: %s", exc, exc_info=True)
        return _retry_or_failure(self, exc, total=len(events_data))

    for event_data in events_data:
        try:
            raw_event_type = event_data.get("event_type")
            raw_payload = event_data.get("payload")
            raw_metadata = event_data.get("metadata", {})
            raw_event_id = event_data.get("event_id")
            if not isinstance(raw_event_type, str):
                raise ValueError("event_type must be a string")
            if not isinstance(raw_payload, dict):
                raise ValueError("payload must be an object")
            if not isinstance(raw_metadata, dict):
                raise ValueError("metadata must be an object")
            if raw_event_id is not None and not isinstance(raw_event_id, str):
                raise ValueError("event_id must be a string")
            raw_occurred_at = event_data.get("occurred_at")
            if raw_occurred_at is not None and not isinstance(raw_occurred_at, str):
                raise ValueError("occurred_at must be a string")
            event = create_event(
                event_type=EventType(raw_event_type),
                payload=raw_payload,
                metadata=raw_metadata,
                event_id=raw_event_id,
                occurred_at=_parse_optional_timestamp(
                    raw_occurred_at,
                    field_name="occurred_at",
                ),
            )
            _persist_event_for_delivery(
                event_store,
                event,
                occurred_at_was_generated=raw_occurred_at is None,
            )

            # 发布
            event_bus.publish(event)

            success_count += 1

        except Exception as exc:
            failed_count += 1
            errors.append(
                {
                    "event_data": event_data,
                    "error": str(exc),
                }
            )
            logger.error(f"Failed to publish event in batch: {exc}")

    return {
        "success": failed_count == 0,
        "total": len(events_data),
        "success_count": success_count,
        "failed_count": failed_count,
        "errors": errors[:10],  # 只返回前 10 个错误
    }


# ========== 异步事件重放 ==========


@_celery_task(
    name="events.replay_events_async",
    max_retries=2,
)
def replay_events_async(
    self: _BoundTaskProtocol,
    event_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 1000,
    target_handler_class: str | None = None,
) -> dict[str, Any]:
    """
    异步重放事件

    Args:
        self: Celery 任务实例
        event_type: 事件类型（可选）
        since: 起始时间（ISO 格式，可选）
        until: 结束时间（ISO 格式，可选）
        limit: 数量限制
        target_handler_class: 目标处理器类路径（可选）

    Returns:
        执行结果
    """
    try:
        since_dt = _parse_optional_timestamp(since, field_name="since")
        until_dt = _parse_optional_timestamp(until, field_name="until")
        if since_dt is not None and until_dt is not None and since_dt > until_dt:
            raise ValueError("since must not be later than until")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")

        # 获取重放处理器
        replay_handler = get_replay_handler()

        # 解析目标处理器
        target_handler: EventHandler | None = None
        if target_handler_class:
            # 动态导入处理器类
            module_path, class_name = target_handler_class.rsplit(".", 1)
            from importlib import import_module

            module = import_module(module_path)
            candidate_handler = getattr(module, class_name)()
            if not isinstance(candidate_handler, EventHandler):
                raise TypeError(f"Replay handler must inherit EventHandler: {target_handler_class}")
            target_handler = candidate_handler

        if target_handler is None:
            raise ValueError("Replay requires an explicit target_handler_class")

        # 执行重放
        count = replay_handler.replay_to(
            subscriber=target_handler,
            event_types=[EventType(event_type)] if event_type else None,
            since=since_dt,
            until=until_dt,
            limit=limit,
        )

        logger.info(f"Replayed {count} events")

        return {
            "success": True,
            "events_replayed": count,
            "event_type": event_type,
            "replayed_at": timezone.now().isoformat(),
        }

    except (AttributeError, ImportError, TypeError, ValueError) as exc:
        logger.warning("Rejected invalid replay task input: %s", exc)
        return _failure_result(exc)
    except Exception as exc:
        logger.error(f"Failed to replay events: {exc}", exc_info=True)
        return _retry_or_failure(self, exc)


# ========== 异步清理 ==========


@_celery_task(
    name="events.cleanup_old_events",
    max_retries=2,
)
def cleanup_old_events(
    self: _BoundTaskProtocol,
    older_than_days: int = 30,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """
    清理旧事件

    Args:
        self: Celery 任务实例
        older_than_days: 清理多少天前的事件
        batch_size: 批量删除大小

    Returns:
        执行结果
    """
    try:
        if older_than_days < 0:
            raise ValueError("older_than_days must be non-negative")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        event_store = get_event_store()
        deleted_count = event_store.cleanup_old_events(
            older_than_days=older_than_days,
            batch_size=batch_size,
        )

        if deleted_count == 0:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "No old events to delete",
            }

        logger.info(f"Cleaned up {deleted_count} old events (older than {older_than_days} days)")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "older_than_days": older_than_days,
            "cleaned_at": timezone.now().isoformat(),
        }

    except ValueError as exc:
        logger.warning("Rejected invalid event cleanup input: %s", exc)
        return _failure_result(exc)
    except Exception as exc:
        logger.error(f"Failed to cleanup old events: {exc}", exc_info=True)
        return _retry_or_failure(self, exc)


@_celery_task(
    name="events.cleanup_old_snapshots",
    max_retries=2,
)
def cleanup_old_snapshots(
    self: _BoundTaskProtocol,
    older_than_days: int = 90,
    keep_latest: int = 10,
) -> dict[str, Any]:
    """
    清理旧快照

    Args:
        self: Celery 任务实例
        older_than_days: 清理多少天前的快照
        keep_latest: 保留最新的 N 个快照

    Returns:
        执行结果
    """
    try:
        if older_than_days < 0:
            raise ValueError("older_than_days must be non-negative")
        if keep_latest < 0:
            raise ValueError("keep_latest must be non-negative")
        snapshot_store = get_snapshot_store()
        deleted_count = snapshot_store.cleanup_old_snapshots(
            older_than_days=older_than_days,
            keep_latest=keep_latest,
        )

        logger.info(f"Cleaned up {deleted_count} old snapshots")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "older_than_days": older_than_days,
            "keep_latest": keep_latest,
            "cleaned_at": timezone.now().isoformat(),
        }

    except ValueError as exc:
        logger.warning("Rejected invalid snapshot cleanup input: %s", exc)
        return _failure_result(exc)
    except Exception as exc:
        logger.error(f"Failed to cleanup old snapshots: {exc}", exc_info=True)
        return _retry_or_failure(self, exc)


# ========== 定时任务 ==========


@_celery_task(
    name="events.collect_event_metrics",
    max_retries=2,
)
def collect_event_metrics(self: _BoundTaskProtocol) -> dict[str, Any]:
    """
    收集事件指标

    定时任务，用于收集和报告事件总线的运行指标。

    Returns:
        指标数据
    """
    try:
        event_bus = get_event_bus()
        event_store = get_event_store()

        # 获取内存指标
        memory_metrics = event_bus.get_metrics()

        # 获取持久化指标
        stored_metrics = event_store.get_metrics()

        # 计算成功率
        total = memory_metrics.total_processed + memory_metrics.total_failed
        success_rate = (memory_metrics.total_processed / total * 100) if total > 0 else 0.0

        metrics = {
            "memory": {
                "total_published": memory_metrics.total_published,
                "total_processed": memory_metrics.total_processed,
                "total_failed": memory_metrics.total_failed,
                "total_subscribers": memory_metrics.total_subscribers,
                "avg_processing_time_ms": memory_metrics.avg_processing_time_ms,
                "last_event_at": (
                    memory_metrics.last_event_at.isoformat()
                    if memory_metrics.last_event_at
                    else None
                ),
                "success_rate": success_rate,
            },
            "stored": {
                "total_events": stored_metrics.total_events,
                "events_by_type": stored_metrics.events_by_type,
            },
            "collected_at": timezone.now().isoformat(),
        }

        logger.info(
            f"Event metrics collected: {memory_metrics.total_published} published, {memory_metrics.total_processed} processed"
        )

        return {
            "success": True,
            "metrics": metrics,
        }

    except Exception as exc:
        logger.error(f"Failed to collect event metrics: {exc}", exc_info=True)
        return _retry_or_failure(self, exc)


@_celery_task(
    name="events.health_check",
    max_retries=2,
)
def event_bus_health_check(self: _BoundTaskProtocol) -> dict[str, Any]:
    """
    事件总线健康检查

    定时任务，用于检查事件总线的健康状态。

    Returns:
        健康状态
    """
    try:
        event_bus = get_event_bus()

        # 获取指标
        metrics = event_bus.get_metrics()

        total_attempted = metrics.total_processed + metrics.total_failed
        failure_rate = metrics.total_failed / total_attempted if total_attempted > 0 else 0.0
        is_healthy = (
            event_bus.is_running()
            and metrics.total_subscribers > 0
            and failure_rate < 0.1
            and metrics.avg_processing_time_ms < 1000
        )

        return {
            "success": True,
            "is_healthy": is_healthy,
            "metrics": {
                "total_published": metrics.total_published,
                "total_processed": metrics.total_processed,
                "total_failed": metrics.total_failed,
                "total_subscribers": metrics.total_subscribers,
                "avg_processing_time_ms": metrics.avg_processing_time_ms,
                "failure_rate": failure_rate,
            },
            "checked_at": timezone.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Event bus health check failed: {exc}", exc_info=True)
        return _retry_or_failure(
            self,
            exc,
            is_healthy=False,
            checked_at=timezone.now().isoformat(),
        )
