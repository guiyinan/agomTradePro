"""
Events Domain Interfaces

定义事件模块的仓储协议，供 Application 层依赖注入使用。

架构约束：
- Domain 层定义接口，Infrastructure 层实现
- Application 层通过 Protocol 依赖抽象，而非具体实现
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from .entities import DomainEvent


class FailedEventRepositoryProtocol(Protocol):
    """
    失败事件仓储协议

    管理失败事件的持久化操作。

    Example:
        >>> repo: FailedEventRepositoryProtocol = get_failed_event_repository()
        >>> events = repo.find_pending_events(limit=10)
    """

    def save(
        self,
        event: DomainEvent,
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
        ...

    def get_by_id(self, event_db_id: int) -> dict[str, Any] | None:
        """
        按 ID 获取失败事件

        Args:
            event_db_id: 数据库 ID

        Returns:
            失败事件字典或 None
        """
        ...

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
        ...

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
        ...

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
        ...

    def mark_success(self, event_db_id: int) -> bool:
        """
        标记为成功

        Args:
            event_db_id: 数据库 ID

        Returns:
            是否更新成功
        """
        ...

    def cleanup_old_events(self, days: int) -> int:
        """
        清理旧的失败事件记录

        Args:
            days: 保留天数

        Returns:
            删除的记录数
        """
        ...


class AlphaCandidateRepositoryProtocol(Protocol):
    """
    Alpha 候选仓储协议（跨模块）

    定义 events 模块对 alpha_trigger 模块的访问接口。
    注意：这是 alpha_trigger.AlphaCandidateRepository 的协议抽象。
    """

    def update_last_decision_request_id(
        self,
        candidate_id: str,
        request_id: str,
    ) -> bool:
        """
        更新候选的最后决策请求 ID

        Args:
            candidate_id: 候选 ID
            request_id: 决策请求 ID

        Returns:
            是否更新成功
        """
        ...

    def update_status_to_rejected(
        self,
        candidate_id: str,
    ) -> bool:
        """
        更新候选状态为已拒绝

        Args:
            candidate_id: 候选 ID

        Returns:
            是否更新成功
        """
        ...

    def update_status_to_executed(
        self,
        candidate_id: str,
    ) -> bool:
        """
        更新候选状态为已执行

        Args:
            candidate_id: 候选 ID

        Returns:
            是否更新成功
        """
        ...

    def update_execution_status_to_failed(
        self,
        candidate_id: str,
    ) -> bool:
        """
        更新候选执行状态为失败（保留 ACTIONABLE 状态）

        Args:
            candidate_id: 候选 ID

        Returns:
            是否更新成功
        """
        ...


class DecisionRequestRepositoryProtocol(Protocol):
    """
    决策请求仓储协议（跨模块）

    定义 events 模块对 decision_rhythm 模块的访问接口。
    注意：这是 decision_rhythm.DecisionRequestRepository 的协议抽象。
    """

    def update_execution_status_to_executed(
        self,
        request_id: str,
        execution_ref: dict[str, Any] | None,
    ) -> bool:
        """
        更新请求执行状态为已执行

        Args:
            request_id: 请求 ID
            execution_ref: 执行引用

        Returns:
            是否更新成功
        """
        ...

    def update_execution_status_to_failed(
        self,
        request_id: str,
    ) -> bool:
        """
        更新请求执行状态为失败

        Args:
            request_id: 请求 ID

        Returns:
            是否更新成功
        """
        ...


class DecisionExecutionSyncRepositoryProtocol(Protocol):
    """Infrastructure-coordinated write model for decision execution status sync."""

    def sync_executed(
        self,
        *,
        request_id: str,
        execution_ref: dict[str, Any] | None,
        candidate_id: str | None,
    ) -> bool:
        """Persist all writes for a DECISION_EXECUTED event atomically."""
        ...

    def sync_failed(
        self,
        *,
        request_id: str,
        candidate_id: str | None,
        error_message: str | None,
    ) -> bool:
        """Persist all writes for a DECISION_EXECUTION_FAILED event atomically."""
        ...
