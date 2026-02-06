"""
Events Application Tasks

事件 Celery 异步任务定义。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from celery import shared_task
from celery.utils.log import get_task_logger

from ..domain.entities import (
    DomainEvent,
    EventType,
    create_event,
)
from ..domain.services import get_event_bus
from ..infrastructure.event_store import (
    DatabaseEventStore,
    get_event_store,
    get_replay_handler,
)


logger = get_task_logger(__name__)


# ========== 异步事件发布 ==========


@shared_task(
    name="events.publish_event_async",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def publish_event_async(
    self,
    event_type: str,
    payload: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    event_id: Optional[str] = None,
    occurred_at: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> Dict[str, Any]:
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
        # 解析时间
        occurred_dt = None
        if occurred_at:
            try:
                occurred_dt = datetime.fromisoformat(occurred_at.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid occurred_at format: {occurred_at}")

        # 创建事件
        event = create_event(
            event_type=EventType(event_type),
            payload=payload,
            metadata=metadata or {},
            event_id=event_id,
            occurred_at=occurred_dt,
        )

        # 添加关联 ID
        if correlation_id:
            event = event.with_correlation_id(correlation_id)
        if causation_id:
            event = event.with_causation_id(causation_id)

        # 获取事件总线和存储
        event_bus = get_event_bus()
        event_store = get_event_store()

        # 持久化事件
        event_store.append(event)

        # 发布事件
        event_bus.publish(event)

        logger.info(f"Event published async: {event.event_id} ({event_type})")

        return {
            "success": True,
            "event_id": event.event_id,
            "event_type": event_type,
            "published_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Failed to publish event async: {exc}", exc_info=True)

        # 重试
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {
            "success": False,
            "event_type": event_type,
            "error": str(exc),
            "retries": self.request.retries,
        }


@shared_task(
    name="events.publish_batch_events_async",
    bind=True,
    max_retries=3,
)
def publish_batch_events_async(
    self,
    events_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
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
    errors = []

    event_bus = get_event_bus()
    event_store = get_event_store()

    for event_data in events_data:
        try:
            event = create_event(
                event_type=EventType(event_data["event_type"]),
                payload=event_data["payload"],
                metadata=event_data.get("metadata", {}),
                event_id=event_data.get("event_id"),
            )

            # 持久化
            event_store.append(event)

            # 发布
            event_bus.publish(event)

            success_count += 1

        except Exception as exc:
            failed_count += 1
            errors.append({
                "event_data": event_data,
                "error": str(exc),
            })
            logger.error(f"Failed to publish event in batch: {exc}")

    return {
        "success": True,
        "total": len(events_data),
        "success_count": success_count,
        "failed_count": failed_count,
        "errors": errors[:10],  # 只返回前 10 个错误
    }


# ========== 异步事件重放 ==========


@shared_task(
    name="events.replay_events_async",
    bind=True,
    max_retries=2,
)
def replay_events_async(
    self,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 1000,
    target_handler_class: Optional[str] = None,
) -> Dict[str, Any]:
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
        # 解析时间
        since_dt = None
        until_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid since format: {since}")
        if until:
            try:
                until_dt = datetime.fromisoformat(until.replace('Z', '+00:00'))
            except ValueError:
                logger.warning(f"Invalid until format: {until}")

        # 获取重放处理器
        replay_handler = get_replay_handler()

        # 解析目标处理器
        target_handler = None
        if target_handler_class:
            # 动态导入处理器类
            module_path, class_name = target_handler_class.rsplit(".", 1)
            from importlib import import_module
            module = import_module(module_path)
            target_handler = getattr(module, class_name)()

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
            "replayed_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Failed to replay events: {exc}", exc_info=True)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        return {
            "success": False,
            "error": str(exc),
            "retries": self.request.retries,
        }


# ========== 异步清理 ==========


@shared_task(
    name="events.cleanup_old_events",
    bind=True,
)
def cleanup_old_events(
    self,
    older_than_days: int = 30,
    batch_size: int = 1000,
) -> Dict[str, Any]:
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
        from datetime import timedelta
        from django.db import transaction
        from ..infrastructure.event_store import StoredEventModel

        cutoff = datetime.now() - timedelta(days=older_than_days)

        # 获取要删除的事件 ID
        event_ids = list(
            StoredEventModel.objects
            .filter(occurred_at__lt=cutoff)
            .values_list("event_id", flat=True)[:batch_size]
        )

        if not event_ids:
            return {
                "success": True,
                "deleted_count": 0,
                "message": "No old events to delete",
            }

        # 批量删除
        with transaction.atomic():
            deleted_count, _ = StoredEventModel.objects.filter(
                event_id__in=event_ids
            ).delete()

        logger.info(f"Cleaned up {deleted_count} old events (older than {older_than_days} days)")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "older_than_days": older_than_days,
            "cleaned_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Failed to cleanup old events: {exc}", exc_info=True)
        return {
            "success": False,
            "error": str(exc),
        }


@shared_task(
    name="events.cleanup_old_snapshots",
    bind=True,
)
def cleanup_old_snapshots(
    self,
    older_than_days: int = 90,
    keep_latest: int = 10,
) -> Dict[str, Any]:
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
        from datetime import timedelta
        from ..infrastructure.event_store import EventSnapshotModel

        cutoff = datetime.now() - timedelta(days=older_than_days)

        # 获取所有快照
        snapshots = EventSnapshotModel.objects.filter(
            created_at__lt=cutoff
        )

        deleted_count = 0

        # 按聚合根分组
        from django.db.models import Min, Max
        aggregates = snapshots.values("aggregate_type", "aggregate_id").distinct()

        for agg in aggregates:
            # 获取该聚合根的快照
            agg_snapshots = list(
                EventSnapshotModel.objects
                .filter(
                    aggregate_type=agg["aggregate_type"],
                    aggregate_id=agg["aggregate_id"],
                    created_at__lt=cutoff,
                )
                .order_by("-version")
            )

            # 保留最新的 N 个
            if len(agg_snapshots) > keep_latest:
                to_delete = agg_snapshots[keep_latest:]
                for snapshot in to_delete:
                    snapshot.delete()
                    deleted_count += 1

        logger.info(f"Cleaned up {deleted_count} old snapshots")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "older_than_days": older_than_days,
            "keep_latest": keep_latest,
            "cleaned_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Failed to cleanup old snapshots: {exc}", exc_info=True)
        return {
            "success": False,
            "error": str(exc),
        }


# ========== 定时任务 ==========


@shared_task(
    name="events.collect_event_metrics",
)
def collect_event_metrics() -> Dict[str, Any]:
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
                "last_event_at": memory_metrics.last_event_at.isoformat() if memory_metrics.last_event_at else None,
                "success_rate": success_rate,
            },
            "stored": {
                "total_events": stored_metrics.total_events,
                "events_by_type": stored_metrics.events_by_type,
            },
            "collected_at": datetime.now().isoformat(),
        }

        logger.info(f"Event metrics collected: {memory_metrics.total_published} published, {memory_metrics.total_processed} processed")

        return {
            "success": True,
            "metrics": metrics,
        }

    except Exception as exc:
        logger.error(f"Failed to collect event metrics: {exc}", exc_info=True)
        return {
            "success": False,
            "error": str(exc),
        }


@shared_task(
    name="events.health_check",
)
def event_bus_health_check() -> Dict[str, Any]:
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

        # 判断健康状态
        is_healthy = (
            metrics.total_failed < metrics.total_processed * 0.1  # 失败率 < 10%
            and metrics.avg_processing_time_ms < 1000  # 平均处理时间 < 1秒
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
            },
            "checked_at": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error(f"Event bus health check failed: {exc}", exc_info=True)
        return {
            "success": False,
            "is_healthy": False,
            "error": str(exc),
            "checked_at": datetime.now().isoformat(),
        }
