"""
Task Monitor Domain Interfaces

定义任务监控仓储协议。
"""

from datetime import datetime, timedelta
from typing import List, Optional, Protocol

from apps.task_monitor.domain.entities import (
    CeleryHealthStatus,
    SchedulerBootstrapResult,
    SchedulerCatalogSummary,
    ScheduledTaskRecord,
    TaskExecutionRecord,
    TaskStatistics,
)


class TaskRecordRepositoryProtocol(Protocol):
    """任务记录仓储协议"""

    def save(self, record: TaskExecutionRecord) -> str:
        """保存任务执行记录

        Args:
            record: 任务执行记录

        Returns:
            str: 记录 ID
        """
        ...

    def get_by_task_id(self, task_id: str) -> TaskExecutionRecord | None:
        """根据任务 ID 获取记录

        Args:
            task_id: Celery 任务 ID

        Returns:
            Optional[TaskExecutionRecord]: 任务执行记录
        """
        ...

    def list_by_task_name(
        self,
        task_name: str,
        limit: int = 100,
        status: str | None = None
    ) -> list[TaskExecutionRecord]:
        """根据任务名称列出记录

        Args:
            task_name: 任务名称
            limit: 返回数量限制
            status: 状态过滤

        Returns:
            List[TaskExecutionRecord]: 任务执行记录列表
        """
        ...

    def list_recent_failures(
        self,
        hours: int = 24,
        limit: int = 50
    ) -> list[TaskExecutionRecord]:
        """列出最近的失败记录

        Args:
            hours: 最近多少小时
            limit: 返回数量限制

        Returns:
            List[TaskExecutionRecord]: 失败的任务记录列表
        """
        ...

    def get_statistics(
        self,
        task_name: str,
        days: int = 7
    ) -> TaskStatistics | None:
        """获取任务统计信息

        Args:
            task_name: 任务名称
            days: 统计最近多少天

        Returns:
            Optional[TaskStatistics]: 任务统计信息
        """
        ...

    def cleanup_old_records(self, days_to_keep: int = 30) -> int:
        """清理旧记录

        Args:
            days_to_keep: 保留天数

        Returns:
            int: 删除的记录数
        """
        ...


class CeleryHealthCheckerProtocol(Protocol):
    """Celery 健康检查协议"""

    def check_health(self) -> CeleryHealthStatus:
        """检查 Celery 健康状态

        Returns:
            CeleryHealthStatus: 健康状态
        """
        ...


class AlertChannelProtocol(Protocol):
    """告警渠道协议"""

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        metadata: dict | None = None
    ) -> bool:
        """发送告警

        Args:
            level: 告警级别 (info/warning/critical)
            title: 标题
            message: 消息内容
            metadata: 额外元数据

        Returns:
            bool: 是否发送成功
        """
        ...

    def is_available(self) -> bool:
        """检查渠道是否可用

        Returns:
            bool: 是否可用
        """
        ...


class SchedulerRepositoryProtocol(Protocol):
    """周期任务配置仓储协议。"""

    def get_catalog_summary(self) -> SchedulerCatalogSummary:
        """返回周期任务摘要。"""
        ...

    def list_periodic_tasks(self, limit: int = 100) -> list[ScheduledTaskRecord]:
        """返回周期任务列表。"""
        ...


class SchedulerBootstrapGatewayProtocol(Protocol):
    """周期任务初始化网关协议。"""

    def initialize_default_schedules(self) -> SchedulerBootstrapResult:
        """初始化默认周期任务。"""
        ...
