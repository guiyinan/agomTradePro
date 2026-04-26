"""
Event Retry Mechanism

事件重试机制，支持失败事件的后续重放。

架构约束：
- 失败事件写错误日志
- 支持后续重放
- 主事务成功优先，事件发布失败不回滚主事务
- 使用 Repository 模式访问数据库
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..domain.entities import DomainEvent, EventType
from ..domain.interfaces import FailedEventRepositoryProtocol

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
    payload: dict[str, Any]
    metadata: dict[str, Any]
    handler_id: str
    error_message: str
    retry_count: int
    max_retries: int
    next_retry_at: datetime | None
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

    def __init__(
        self,
        max_retries: int = 3,
        base_delay_minutes: int = 5,
        failed_event_repo: FailedEventRepositoryProtocol | None = None,
    ):
        """
        初始化管理器

        Args:
            max_retries: 最大重试次数
            base_delay_minutes: 基础延迟时间（分钟）
            failed_event_repo: 失败事件仓储（可选，默认自动创建）
        """
        self.max_retries = max_retries
        self.base_delay_minutes = base_delay_minutes

        if failed_event_repo is None:
            from ..infrastructure.providers import get_failed_event_repository
            failed_event_repo = get_failed_event_repository()

        self._repo = failed_event_repo

    def record_failure(
        self,
        event: DomainEvent,
        handler_id: str,
        error: Exception,
        traceback_str: str | None = None,
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

        try:
            event_db_id = self._repo.save(
                event=event,
                handler_id=handler_id,
                error_message=str(error),
                error_traceback=traceback_str or traceback.format_exc(),
                max_retries=self.max_retries,
            )

            logger.info(
                f"Recorded failed event: {event.event_id} "
                f"(handler={handler_id}, error={error})"
            )

            # 获取保存的事件并转换为 DTO
            event_dict = self._repo.get_by_id(event_db_id)
            if event_dict:
                return self._dict_to_dto(event_dict)
            else:
                raise RuntimeError(f"Failed to retrieve saved event: {event_db_id}")

        except Exception as e:
            logger.error(f"Failed to record failed event: {e}", exc_info=True)
            raise

    def get_pending_events(
        self,
        limit: int = 100,
        handler_id: str | None = None,
    ) -> list[FailedEventDTO]:
        """
        获取待重试的事件

        Args:
            limit: 最大返回数量
            handler_id: 处理器 ID 过滤（可选）

        Returns:
            失败事件 DTO 列表
        """
        event_dicts = self._repo.find_pending_events(
            limit=limit,
            handler_id=handler_id,
        )

        return [self._dict_to_dto(d) for d in event_dicts]

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
            self._repo.update_status(
                event_db_id=failed_event_dto.id,
                status="RETRYING",
                last_retry_at=datetime.now(UTC),
            )

            # 重建事件对象
            try:
                event_type = EventType(failed_event_dto.event_type)
            except ValueError:
                logger.warning(f"Unknown event type: {failed_event_dto.event_type}")
                event_type = EventType.UNKNOWN

            event = DomainEvent(
                event_id=failed_event_dto.event_id,
                event_type=event_type,
                occurred_at=datetime.now(UTC),  # 使用当前时间
                payload=failed_event_dto.payload,
                metadata=failed_event_dto.metadata,
            )

            # 执行处理器
            handler_callable(event)

            # 重试成功
            self._repo.mark_success(failed_event_dto.id)

            logger.info(
                f"Event retry succeeded: {failed_event_dto.event_id} "
                f"(handler={failed_event_dto.handler_id}, "
                f"attempts={failed_event_dto.retry_count + 1})"
            )

            return True

        except Exception as e:
            # 重试失败
            # 检查是否耗尽重试次数
            is_exhausted = (failed_event_dto.retry_count + 1) >= failed_event_dto.max_retries

            # 计算下次重试时间（指数退避）
            if is_exhausted:
                next_retry_at = None
            else:
                delay_minutes = self.base_delay_minutes * (2 ** (failed_event_dto.retry_count + 1))
                next_retry_at = datetime.now(UTC) + timedelta(minutes=delay_minutes)

            self._repo.increment_retry_count(
                event_db_id=failed_event_dto.id,
                error_message=str(e),
                next_retry_at=next_retry_at,
                is_exhausted=is_exhausted,
            )

            if is_exhausted:
                logger.error(
                    f"Event retry exhausted: {failed_event_dto.event_id} "
                    f"(handler={failed_event_dto.handler_id}, "
                    f"attempts={failed_event_dto.retry_count + 1})"
                )
            else:
                logger.warning(
                    f"Event retry failed: {failed_event_dto.event_id} "
                    f"(handler={failed_event_dto.handler_id}, "
                    f"attempts={failed_event_dto.retry_count + 1}, "
                    f"next_retry_at={next_retry_at})"
                )

            return False

    def retry_pending_events(
        self,
        handler_factory: Callable[[str], Callable[[DomainEvent], None] | None],
        limit: int = 100,
    ) -> dict[str, int]:
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
                event_dict = self._repo.get_by_id(failed_event_dto.id)
                if event_dict and event_dict["status"] == "EXHAUSTED":
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
        return self._repo.cleanup_old_events(days)

    def _dict_to_dto(self, event_dict: dict[str, Any]) -> FailedEventDTO:
        """转换字典为 DTO"""
        return FailedEventDTO(
            id=event_dict["id"],
            event_id=event_dict["event_id"],
            event_type=event_dict["event_type"],
            payload=event_dict["payload"],
            metadata=event_dict["metadata"],
            handler_id=event_dict["handler_id"],
            error_message=event_dict["error_message"],
            retry_count=event_dict["retry_count"],
            max_retries=event_dict["max_retries"],
            next_retry_at=event_dict["next_retry_at"],
            status=event_dict["status"],
        )


# 全局单例
_event_retry_manager: EventRetryManager | None = None


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
