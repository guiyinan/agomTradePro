"""
Events Infrastructure Repositories

实现 Domain 层定义的仓储协议。

这些仓储桥接 Domain 层接口和 Django ORM 模型。
"""

import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from django.core.exceptions import ObjectDoesNotExist
from core.integration.alpha_candidates import (
    AlphaCandidateRepositoryWrapper,
    get_alpha_candidate_repository,
)
from core.integration.decision_requests import (
    DecisionRequestRepositoryWrapper,
    get_decision_request_repository,
)

from ..domain.interfaces import (
    FailedEventRepositoryProtocol,
)
from .models import FailedEventModel

logger = logging.getLogger(__name__)


class FailedEventRepository:
    """
    失败事件仓储

    实现 FailedEventRepositoryProtocol，管理失败事件的持久化。

    Example:
        >>> repo = FailedEventRepository()
        >>> events = repo.find_pending_events(limit=10)
    """

    def __init__(self):
        """初始化仓储"""
        self.model = FailedEventModel

    def save(
        self,
        event,
        handler_id: str,
        error_message: str,
        error_traceback: str | None,
        max_retries: int,
    ) -> int:
        """
        保存失败事件

        Args:
            event: 领域事件
            handler_id: 处理器 ID
            error_message: 错误信息
            error_traceback: 错误堆栈
            max_retries: 最大重试次数

        Returns:
            保存后的数据库 ID
        """
        failed_event = self.model(
            event_id=event.event_id,
            event_type=event.event_type.value,
            payload=event.payload,
            metadata=event.metadata,
            handler_id=handler_id,
            error_message=error_message,
            error_traceback=error_traceback or "",
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=datetime.now(UTC),
            status=self.model.PENDING,
        )
        failed_event.save()

        logger.info(
            f"Failed event saved: {event.event_id} "
            f"(handler={handler_id}, id={failed_event.id})"
        )

        return failed_event.id

    def get_by_id(self, event_db_id: int) -> dict[str, Any] | None:
        """
        按 ID 获取失败事件

        Args:
            event_db_id: 数据库 ID

        Returns:
            失败事件字典或 None
        """
        try:
            model = self.model.objects.get(id=event_db_id)
            return self._to_dict(model)
        except ObjectDoesNotExist:
            return None

    def find_pending_events(
        self,
        limit: int,
        handler_id: str | None,
    ) -> list[dict[str, Any]]:
        """
        查找待重试的事件

        Args:
            limit: 最大返回数量
            handler_id: 处理器 ID 过滤（可选）

        Returns:
            失败事件字典列表
        """
        queryset = self.model.objects.filter(
            status=self.model.PENDING,
            next_retry_at__lte=datetime.now(UTC),
        )

        if handler_id:
            queryset = queryset.filter(handler_id=handler_id)

        failed_events = queryset.order_by("created_at")[:limit]

        return [self._to_dict(fe) for fe in failed_events]

    def update_status(
        self,
        event_db_id: int,
        status: str,
        last_retry_at: datetime | None = None,
    ) -> bool:
        """
        更新事件状态

        Args:
            event_db_id: 数据库 ID
            status: 新状态
            last_retry_at: 最后重试时间（可选）

        Returns:
            是否更新成功
        """
        try:
            model = self.model.objects.get(id=event_db_id)
            model.status = status

            if last_retry_at:
                model.last_retry_at = last_retry_at

            model.save(update_fields=["status", "last_retry_at", "updated_at"])

            return True

        except ObjectDoesNotExist:
            logger.warning(f"Failed event not found: {event_db_id}")
            return False

    def increment_retry_count(
        self,
        event_db_id: int,
        error_message: str,
        next_retry_at: datetime | None,
        is_exhausted: bool,
    ) -> bool:
        """
        增加重试计数

        Args:
            event_db_id: 数据库 ID
            error_message: 错误信息
            next_retry_at: 下次重试时间
            is_exhausted: 是否已耗尽重试次数

        Returns:
            是否更新成功
        """
        try:
            model = self.model.objects.get(id=event_db_id)
            model.retry_count += 1
            model.error_message = error_message

            if is_exhausted:
                model.status = self.model.EXHAUSTED
            else:
                model.next_retry_at = next_retry_at
                model.status = self.model.PENDING

            model.save()

            return True

        except ObjectDoesNotExist:
            logger.warning(f"Failed event not found: {event_db_id}")
            return False

    def mark_success(self, event_db_id: int) -> bool:
        """
        标记为成功

        Args:
            event_db_id: 数据库 ID

        Returns:
            是否更新成功
        """
        try:
            model = self.model.objects.get(id=event_db_id)
            model.status = self.model.SUCCESS
            model.save(update_fields=["status", "updated_at"])

            return True

        except ObjectDoesNotExist:
            logger.warning(f"Failed event not found: {event_db_id}")
            return False

    def cleanup_old_events(self, days: int) -> int:
        """
        清理旧的失败事件记录

        Args:
            days: 保留天数

        Returns:
            删除的记录数
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        deleted, _ = self.model.objects.filter(
            status__in=[self.model.SUCCESS, self.model.EXHAUSTED],
            updated_at__lt=cutoff_date,
        ).delete()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old failed event records")

        return deleted

    def _to_dict(self, model: FailedEventModel) -> dict[str, Any]:
        """转换 ORM 模型为字典"""
        return {
            "id": model.id,
            "event_id": model.event_id,
            "event_type": model.event_type,
            "payload": model.payload,
            "metadata": model.metadata,
            "handler_id": model.handler_id,
            "error_message": model.error_message,
            "retry_count": model.retry_count,
            "max_retries": model.max_retries,
            "next_retry_at": model.next_retry_at,
            "status": model.status,
        }


# 便捷函数

def get_failed_event_repository() -> FailedEventRepository:
    """获取失败事件仓储实例"""
    return FailedEventRepository()


def get_alpha_candidate_repository() -> AlphaCandidateRepositoryWrapper:
    """获取 Alpha 候选仓储包装器实例"""
    return AlphaCandidateRepositoryWrapper()
