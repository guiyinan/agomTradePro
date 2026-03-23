"""
Event Store Implementation

基于数据库的事件存储实现。
支持事件持久化、重放和快照功能。

这是 Infrastructure 层的实现，桥接 Domain 层和 Django ORM。
"""

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Dict, List, Optional

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.utils import timezone

from ..domain.entities import (
    DomainEvent,
    EventBusConfig,
    EventMetrics,
    EventSnapshot,
    EventType,
)

logger = logging.getLogger(__name__)


# ========== Django ORM Models ==========


class StoredEventModel(models.Model):
    """
    存储事件 ORM 模型

    持久化领域事件。

    Attributes:
        event_id: 事件 ID
        event_type: 事件类型
        payload: 事件负载（JSON）
        metadata: 事件元数据（JSON）
        correlation_id: 关联 ID
        causation_id: 因果 ID
        occurred_at: 事件发生时间
        created_at: 存储时间
        version: 事件版本（用于乐观锁）
    """

    event_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="事件唯一标识符"
    )

    event_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="事件类型"
    )

    payload = models.JSONField(
        help_text="事件负载"
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="事件元数据"
    )

    correlation_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        help_text="关联 ID（用于关联多个事件）"
    )

    causation_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        help_text="因果 ID（用于追踪事件链）"
    )

    occurred_at = models.DateTimeField(
        db_index=True,
        help_text="事件发生时间"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="存储时间"
    )

    version = models.IntegerField(
        default=1,
        help_text="事件版本"
    )

    class Meta:
        db_table = "stored_event"
        verbose_name = "存储事件"
        verbose_name_plural = "存储事件"
        ordering = ["-occurred_at", "-created_at"]
        indexes = [
            models.Index(fields=["event_type", "-occurred_at"]),
            models.Index(fields=["correlation_id", "-occurred_at"]),
            models.Index(fields=["occurred_at"]),
        ]

    def __str__(self):
        return f"StoredEvent({self.event_id}, {self.event_type}, {self.occurred_at})"


class EventSnapshotModel(models.Model):
    """
    事件快照 ORM 模型

    存储事件处理的快照状态。

    Attributes:
        snapshot_id: 快照 ID
        aggregate_type: 聚合根类型
        aggregate_id: 聚合根 ID
        version: 版本号
        state: 状态（JSON）
        created_at: 创建时间
    """

    snapshot_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="快照唯一标识符"
    )

    aggregate_type = models.CharField(
        max_length=64,
        db_index=True,
        help_text="聚合根类型"
    )

    aggregate_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="聚合根 ID"
    )

    version = models.IntegerField(
        help_text="版本号"
    )

    state = models.JSONField(
        help_text="状态"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    class Meta:
        db_table = "event_snapshot"
        verbose_name = "事件快照"
        verbose_name_plural = "事件快照"
        ordering = ["-version"]
        indexes = [
            models.Index(fields=["aggregate_type", "aggregate_id", "-version"]),
        ]
        unique_together = [["aggregate_type", "aggregate_id", "version"]]

    def __str__(self):
        return f"EventSnapshot({self.snapshot_id}, {self.aggregate_type}, v{self.version})"


class EventSubscriptionModel(models.Model):
    """
    事件订阅 ORM 模型

    存储事件订阅配置。

    Attributes:
        subscription_id: 订阅 ID
        handler_id: 处理器 ID
        event_types: 订阅的事件类型（JSON）
        is_active: 是否激活
        created_at: 创建时间
        updated_at: 更新时间
    """

    subscription_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="订阅唯一标识符"
    )

    handler_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="处理器 ID"
    )

    event_types = models.JSONField(
        help_text="订阅的事件类型列表"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="是否激活"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="创建时间"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="更新时间"
    )

    class Meta:
        db_table = "event_subscription"
        verbose_name = "事件订阅"
        verbose_name_plural = "事件订阅"
        ordering = ["handler_id"]

    def __str__(self):
        return f"EventSubscription({self.subscription_id}, {self.handler_id})"


# ========== Database Event Store ==========


class DatabaseEventStore:
    """
    基于数据库的事件存储

    实现事件持久化、查询和重放功能。

    Attributes:
        model: Django ORM 模型

    Example:
        >>> store = DatabaseEventStore()
        >>> store.append(event)
        >>> events = store.get_events(event_type=EventType.REGIME_CHANGED)
    """

    def __init__(self):
        """初始化事件存储"""
        self.model = StoredEventModel

    def append(self, event: DomainEvent) -> bool:
        """
        追加事件

        Args:
            event: 领域事件

        Returns:
            是否成功
        """
        try:
            model = self.model(
                event_id=event.event_id,
                event_type=event.event_type.value,
                payload=event.payload,
                metadata=event.metadata,
                correlation_id=event.metadata.get("correlation_id"),
                causation_id=event.metadata.get("causation_id"),
                occurred_at=event.occurred_at,
                version=event.version,
            )

            model.save()

            logger.debug(f"Event stored: {event.event_id} ({event.event_type.value})")

            return True

        except Exception as e:
            logger.error(f"Failed to store event: {e}", exc_info=True)
            return False

    def append_batch(self, events: list[DomainEvent]) -> int:
        """
        批量追加事件

        Args:
            events: 领域事件列表

        Returns:
            成功存储的数量
        """
        count = 0

        for event in events:
            if self.append(event):
                count += 1

        return count

    def get_by_id(self, event_id: str) -> DomainEvent | None:
        """
        按 ID 获取事件

        Args:
            event_id: 事件 ID

        Returns:
            领域事件或 None
        """
        try:
            model = self.model.objects.get(event_id=event_id)
            return self._to_domain_event(model)
        except self.model.DoesNotExist:
            return None

    def get_events(
        self,
        event_type: EventType | None = None,
        event_types: list[EventType] | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        """
        获取事件列表

        Args:
            event_type: 事件类型过滤（可选）
            event_types: 事件类型列表过滤（可选）
            correlation_id: 关联 ID 过滤（可选）
            since: 起始时间（可选）
            until: 结束时间（可选）
            limit: 返回数量限制

        Returns:
            领域事件列表
        """
        queryset = self.model.objects.all()

        if event_type:
            queryset = queryset.filter(event_type=event_type.value)

        if event_types:
            type_values = [t.value for t in event_types]
            queryset = queryset.filter(event_type__in=type_values)

        if correlation_id:
            queryset = queryset.filter(correlation_id=correlation_id)

        if since:
            queryset = queryset.filter(occurred_at__gte=since)

        if until:
            queryset = queryset.filter(occurred_at__lte=until)

        models = queryset.order_by("-occurred_at", "-created_at")[:limit]

        return [self._to_domain_event(m) for m in models]

    def get_by_correlation(self, correlation_id: str) -> list[DomainEvent]:
        """
        按关联 ID 获取事件

        Args:
            correlation_id: 关联 ID

        Returns:
            领域事件列表
        """
        models = (
            self.model.objects
            .filter(correlation_id=correlation_id)
            .order_by("occurred_at", "created_at")
        )

        return [self._to_domain_event(m) for m in models]

    def get_metrics(
        self,
        since: datetime | None = None,
    ) -> EventMetrics:
        """
        获取事件指标

        Args:
            since: 起始时间（可选）

        Returns:
            事件指标
        """
        queryset = self.model.objects.all()

        if since:
            queryset = queryset.filter(occurred_at__gte=since)

        total = queryset.count()

        # 按类型分组
        by_type = {}
        for model in queryset:
            by_type[model.event_type] = by_type.get(model.event_type, 0) + 1

        return EventMetrics(
            total_published=total,
            total_processed=total,
            total_failed=0,
            total_subscribers=0,
            avg_processing_time_ms=0.0,
            last_event_at=None,
            total_events=total,
            events_by_type=by_type,
        )

    def _to_domain_event(self, model: StoredEventModel) -> DomainEvent:
        """转换 ORM 模型为领域事件"""
        try:
            event_type = EventType(model.event_type)
        except ValueError:
            # 未知类型，使用 UNKNOWN 而不是映射到业务事件类型
            # 保留原始事件类型字符串到 metadata 中以便追溯
            logger.warning(f"Unknown event type: {model.event_type}, using UNKNOWN")
            event_type = EventType.UNKNOWN

        # 确保 metadata 中包含 correlation_id 和 causation_id
        metadata = dict(model.metadata) if model.metadata else {}
        if model.correlation_id:
            metadata["correlation_id"] = model.correlation_id
        if model.causation_id:
            metadata["causation_id"] = model.causation_id

        return DomainEvent(
            event_type=event_type,
            payload=model.payload,
            event_id=model.event_id,
            occurred_at=model.occurred_at,
            metadata=metadata,
            version=model.version,
        )


# ========== Snapshot Store ==========


class SnapshotStore:
    """
    快照存储

    管理聚合根快照的持久化。

    Attributes:
        model: Django ORM 模型

    Example:
        >>> store = SnapshotStore()
        >>> store.save_snapshot(aggregate_type, aggregate_id, version, state)
        >>> snapshot = store.get_latest_snapshot(aggregate_type, aggregate_id)
    """

    def __init__(self):
        """初始化快照存储"""
        self.model = EventSnapshotModel

    def save_snapshot(
        self,
        aggregate_type: str,
        aggregate_id: str,
        version: int,
        state: dict[str, Any],
    ) -> str | None:
        """
        保存快照

        Args:
            aggregate_type: 聚合根类型
            aggregate_id: 聚合根 ID
            version: 版本号
            state: 状态

        Returns:
            快照 ID 或 None
        """
        import uuid

        try:
            # 检查是否已存在
            existing = (
                self.model.objects
                .filter(
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                    version=version,
                )
                .first()
            )

            if existing:
                # 更新
                existing.state = state
                existing.save()
                return existing.snapshot_id

            # 创建
            snapshot_id = f"snapshot_{uuid.uuid4().hex[:12]}"

            model = self.model(
                snapshot_id=snapshot_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                version=version,
                state=state,
            )

            model.save()

            logger.debug(
                f"Snapshot saved: {snapshot_id} "
                f"({aggregate_type}, {aggregate_id}, v{version})"
            )

            return snapshot_id

        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}", exc_info=True)
            return None

    def get_latest_snapshot(
        self,
        aggregate_type: str,
        aggregate_id: str,
    ) -> EventSnapshot | None:
        """
        获取最新快照

        Args:
            aggregate_type: 聚合根类型
            aggregate_id: 聚合根 ID

        Returns:
            事件快照或 None
        """
        try:
            model = (
                self.model.objects
                .filter(
                    aggregate_type=aggregate_type,
                    aggregate_id=aggregate_id,
                )
                .order_by("-version")
                .first()
            )

            if model:
                return EventSnapshot(
                    snapshot_id=model.snapshot_id,
                    aggregate_type=model.aggregate_type,
                    aggregate_id=model.aggregate_id,
                    version=model.version,
                    state=model.state,
                    created_at=model.created_at,
                )
            return None

        except Exception as e:
            logger.error(f"Failed to get snapshot: {e}", exc_info=True)
            return None

    def get_snapshot(
        self,
        aggregate_type: str,
        aggregate_id: str,
        version: int,
    ) -> EventSnapshot | None:
        """
        获取指定版本快照

        Args:
            aggregate_type: 聚合根类型
            aggregate_id: 聚合根 ID
            version: 版本号

        Returns:
            事件快照或 None
        """
        try:
            model = self.model.objects.get(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                version=version,
            )

            return EventSnapshot(
                snapshot_id=model.snapshot_id,
                aggregate_type=model.aggregate_type,
                aggregate_id=model.aggregate_id,
                version=model.version,
                state=model.state,
                created_at=model.created_at,
            )

        except self.model.DoesNotExist:
            return None

    def delete_snapshots(
        self,
        aggregate_type: str,
        aggregate_id: str,
        keep_latest: int = 1,
    ) -> int:
        """
        删除旧快照

        Args:
            aggregate_type: 聚合根类型
            aggregate_id: 聚合根 ID
            keep_latest: 保留最新 N 个快照

        Returns:
            删除的数量
        """
        # 获取所有快照，按版本降序
        snapshots = (
            self.model.objects
            .filter(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
            )
            .order_by("-version")
        )

        # 保留最新的 N 个
        to_keep = snapshots[:keep_latest]
        to_delete = snapshots[keep_latest:]

        count = 0
        for snapshot in to_delete:
            snapshot.delete()
            count += 1

        if count > 0:
            logger.info(
                f"Deleted {count} old snapshots for "
                f"{aggregate_type}:{aggregate_id}"
            )

        return count


# ========== Event Replay ==========


class EventReplayHandler:
    """
    事件重放处理器

    支持从事件存储重放事件到处理器。

    Attributes:
        event_store: 事件存储

    Example:
        >>> handler = EventReplayHandler(store)
        >>> handler.replay_to(subscriber, since=start_date)
    """

    def __init__(self, event_store: DatabaseEventStore):
        """
        初始化处理器

        Args:
            event_store: 事件存储
        """
        self.event_store = event_store

    def replay_to(
        self,
        subscriber,
        event_types: list[EventType] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> int:
        """
        重放事件到订阅器

        Args:
            subscriber: 事件订阅器
            event_types: 事件类型过滤（可选）
            since: 起始时间（可选）
            until: 结束时间（可选）
            limit: 限制数量

        Returns:
            重放的事件数量
        """
        # 获取需要重放的事件
        events = self.event_store.get_events(
            event_types=event_types,
            since=since,
            until=until,
            limit=limit,
        )

        # 按时间顺序重放
        events_sorted = sorted(events, key=lambda e: (e.occurred_at, e.event_id))

        count = 0
        for event in events_sorted:
            try:
                if subscriber.can_handle(event.event_type):
                    subscriber.handle(event)
                    count += 1
            except Exception as e:
                logger.error(
                    f"Error replaying event {event.event_id}: {e}",
                    exc_info=True
                )

        logger.info(f"Replayed {count} events to {subscriber}")

        return count


# ========== Convenience Functions ==========


def get_event_store() -> DatabaseEventStore:
    """获取事件存储实例"""
    return DatabaseEventStore()


class InMemoryEventStore:
    """
    轻量内存事件存储。

    主要用于开发/测试环境初始化事件总线，避免在 URL 导入阶段依赖数据库表。
    """

    def __init__(self):
        self._events: list[DomainEvent] = []

    def append(self, event: DomainEvent) -> bool:
        self._events.append(event)
        return True

    def append_batch(self, events: list[DomainEvent]) -> int:
        self._events.extend(events)
        return len(events)

    def get_events(
        self,
        event_type: EventType | None = None,
        event_types: list[EventType] | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[DomainEvent]:
        events = self._events

        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if event_types:
            allowed = set(event_types)
            events = [e for e in events if e.event_type in allowed]
        if correlation_id:
            events = [e for e in events if e.metadata.get("correlation_id") == correlation_id]
        if since:
            events = [e for e in events if e.occurred_at >= since]
        if until:
            events = [e for e in events if e.occurred_at <= until]

        return events[: max(limit, 0)]

    def get_metrics(self, since: datetime | None = None) -> EventMetrics:
        events = self.get_events(since=since, limit=len(self._events))
        return EventMetrics(
            total_published=len(events),
            total_processed=len(events),
            total_failed=0,
            total_subscribers=0,
            avg_processing_time_ms=0.0,
            last_event_at=None,
            total_events=len(events),
            events_by_type={},
        )


def get_snapshot_store() -> SnapshotStore:
    """获取快照存储实例"""
    return SnapshotStore()


def get_replay_handler() -> EventReplayHandler:
    """获取重放处理器实例"""
    return EventReplayHandler(get_event_store())
