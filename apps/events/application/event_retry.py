"""
Event Retry Mechanism

事件重试机制，支持失败事件的后续重放。

架构约束：
- 失败事件写错误日志
- 支持后续重放
- 主事务成功优先，事件发布失败不回滚主事务
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..domain.entities import DomainEvent, EventType
from ..infrastructure.models import FailedEventModel


logger = logging.getLogger(__name__)


@dataclass
class FailedEventDTO:
    """
    失败事件传输对象

    Attributes:
        id: 数据库 ID
        event_id: 事件 ID
        event_type: 事件类型
        payload: 事件负载
        metadata: 事件元数据
        handler_id: 处理器 ID
        error_message: 错误信息
        retry_count: 重试次数
        max_retries: 最大重试次数
        next_retry_at: 下次重试时间
        status: 状态
    """
    id: int
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any]
    handler_id: str
    error_message: str
    retry_count: int
    max_retries: int
    next_retry_at: Optional[datetime]
    status: str


class EventRetryManager:
    """
    事件重试管理器

    管理失败事件的重试机制。

    Features:
    1. 记录失败事件
    2. 支持重试策略（指数退避）
    3. 批量重试
    4. 重试次数限制

    Example:
        >>> manager = EventRetryManager()
        >>> manager.record_failure(event, handler_id, error)
        >>> manager.retry_pending_events()
    """

    def __init__(self, max_retries: int = 3, base_delay_minutes: int = 5):
        """
        初始化管理器

        Args:
            max_retries: 最大重试次数
            base_delay_minutes: 基础延迟时间（分钟）
        """
        self.max_retries = max_retries
        self.base_delay_minutes = base_delay_minutes

    def record_failure(
        self,
        event: DomainEvent,
        handler_id: str,
        error: Exception,
        traceback_str: Optional[str] = None,
    ) -> FailedEventDTO:
        """
        记录失败事件

        Args:
            event: 领域事件
            handler_id: 处理器 ID
            error: 异常对象
            traceback_str: 错误堆栈（可选）

        Returns:
            失败事件 DTO
        """
        import traceback

        # 计算下次重试时间（指数退避）
        next_retry_at = datetime.now(timezone.utc)

        try:
            failed_event = FailedEventModel(
                event_id=event.event_id,
                event_type=event.event_type.value,
                payload=event.payload,
                metadata=event.metadata,
                handler_id=handler_id,
                error_message=str(error),
                error_traceback=traceback_str or traceback.format_exc(),
                retry_count=0,
                max_retries=self.max_retries,
                next_retry_at=next_retry_at,
                status=FailedEventModel.PENDING,
            )
            failed_event.save()

            logger.info(
                f"Recorded failed event: {event.event_id} "
                f"(handler={handler_id}, error={error})"
            )

            return self._to_dto(failed_event)

        except Exception as e:
            logger.error(f"Failed to record failed event: {e}", exc_info=True)
            raise

    def get_pending_events(
        self,
        limit: int = 100,
        handler_id: Optional[str] = None,
    ) -> List[FailedEventDTO]:
        """
        获取待重试的事件

        Args:
            limit: 最大返回数量
            handler_id: 处理器 ID 过滤（可选）

        Returns:
            失败事件 DTO 列表
        """
        queryset = FailedEventModel.objects.filter(
            status=FailedEventModel.PENDING,
            next_retry_at__lte=datetime.now(timezone.utc),
        )

        if handler_id:
            queryset = queryset.filter(handler_id=handler_id)

        failed_events = queryset.order_by("created_at")[:limit]

        return [self._to_dto(fe) for fe in failed_events]

    def retry_event(
        self,
        failed_event_dto: FailedEventDTO,
        handler_callable: Callable[[DomainEvent], None],
    ) -> bool:
        """
        重试单个事件

        Args:
            failed_event_dto: 失败事件 DTO
            handler_callable: 处理器可调用对象

        Returns:
            是否重试成功
        """
        try:
            # 更新状态为重试中
            failed_event = FailedEventModel.objects.get(id=failed_event_dto.id)
            failed_event.status = FailedEventModel.RETRYING
            failed_event.last_retry_at = datetime.now(timezone.utc)
            failed_event.save(update_fields=["status", "last_retry_at", "updated_at"])

            # 重建事件对象
            try:
                event_type = EventType(failed_event.event_type)
            except ValueError:
                logger.warning(f"Unknown event type: {failed_event.event_type}")
                event_type = EventType.UNKNOWN

            event = DomainEvent(
                event_id=failed_event.event_id,
                event_type=event_type,
                occurred_at=datetime.now(timezone.utc),  # 使用当前时间
                payload=failed_event.payload,
                metadata=failed_event.metadata,
            )

            # 执行处理器
            handler_callable(event)

            # 重试成功
            failed_event.status = FailedEventModel.SUCCESS
            failed_event.save(update_fields=["status", "updated_at"])

            logger.info(
                f"Event retry succeeded: {failed_event.event_id} "
                f"(handler={failed_event.handler_id}, "
                f"attempts={failed_event.retry_count + 1})"
            )

            return True

        except Exception as e:
            # 重试失败
            failed_event = FailedEventModel.objects.get(id=failed_event_dto.id)
            failed_event.retry_count += 1
            failed_event.error_message = str(e)

            # 检查是否耗尽重试次数
            if failed_event.retry_count >= failed_event.max_retries:
                failed_event.status = FailedEventModel.EXHAUSTED
                logger.error(
                    f"Event retry exhausted: {failed_event.event_id} "
                    f"(handler={failed_event.handler_id}, "
                    f"attempts={failed_event.retry_count})"
                )
            else:
                # 计算下次重试时间（指数退避）
                delay_minutes = self.base_delay_minutes * (2 ** failed_event.retry_count)
                failed_event.next_retry_at = (
                    datetime.now(timezone.utc) +
                    __import__('datetime').timedelta(minutes=delay_minutes)
                )
                failed_event.status = FailedEventModel.PENDING
                logger.warning(
                    f"Event retry failed: {failed_event.event_id} "
                    f"(handler={failed_event.handler_id}, "
                    f"attempts={failed_event.retry_count}, "
                    f"next_retry_at={failed_event.next_retry_at})"
                )

            failed_event.save()

            return False

    def retry_pending_events(
        self,
        handler_factory: Callable[[str], Optional[Callable[[DomainEvent], None]]],
        limit: int = 100,
    ) -> Dict[str, int]:
        """
        批量重试待重试的事件

        Args:
            handler_factory: 处理器工厂函数，根据 handler_id 返回处理器
            limit: 最大重试数量

        Returns:
            统计信息 {"success": int, "failed": int, "exhausted": int}
        """
        pending_events = self.get_pending_events(limit=limit)

        stats = {"success": 0, "failed": 0, "exhausted": 0}

        for failed_event_dto in pending_events:
            # 获取处理器
            handler = handler_factory(failed_event_dto.handler_id)
            if handler is None:
                logger.warning(
                    f"Handler not found for failed event: "
                    f"{failed_event_dto.event_id} (handler={failed_event_dto.handler_id})"
                )
                stats["failed"] += 1
                continue

            # 重试
            success = self.retry_event(failed_event_dto, handler)

            if success:
                stats["success"] += 1
            else:
                # 检查是否耗尽
                failed_event = FailedEventModel.objects.get(id=failed_event_dto.id)
                if failed_event.status == FailedEventModel.EXHAUSTED:
                    stats["exhausted"] += 1
                else:
                    stats["failed"] += 1

        logger.info(
            f"Batch retry completed: "
            f"success={stats['success']}, "
            f"failed={stats['failed']}, "
            f"exhausted={stats['exhausted']}"
        )

        return stats

    def cleanup_old_events(self, days: int = 30) -> int:
        """
        清理旧的失败事件记录

        Args:
            days: 保留天数

        Returns:
            删除的记录数
        """
        cutoff_date = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)

        deleted, _ = FailedEventModel.objects.filter(
            status__in=[FailedEventModel.SUCCESS, FailedEventModel.EXHAUSTED],
            updated_at__lt=cutoff_date,
        ).delete()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old failed event records")

        return deleted

    def _to_dto(self, model: FailedEventModel) -> FailedEventDTO:
        """转换 ORM 模型为 DTO"""
        return FailedEventDTO(
            id=model.id,
            event_id=model.event_id,
            event_type=model.event_type,
            payload=model.payload,
            metadata=model.metadata,
            handler_id=model.handler_id,
            error_message=model.error_message,
            retry_count=model.retry_count,
            max_retries=model.max_retries,
            next_retry_at=model.next_retry_at,
            status=model.status,
        )


# 全局单例
_event_retry_manager: Optional[EventRetryManager] = None


def get_event_retry_manager() -> EventRetryManager:
    """
    获取事件重试管理器单例

    Returns:
        事件重试管理器
    """
    global _event_retry_manager

    if _event_retry_manager is None:
        _event_retry_manager = EventRetryManager()

    return _event_retry_manager
