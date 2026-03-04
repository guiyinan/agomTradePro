"""
Audit Failure Counter Module

审计失败计数器，用于跟踪审计日志写入失败情况，增强可观测性。

Features:
1. 使用 Django cache 作为计数存储（跨进程共享）
2. 提供失败计数和重置功能
3. 自动记录失败原因和时间戳
4. 支持健康检查集成

使用示例:
    >>> from apps.audit.infrastructure.failure_counter import get_audit_failure_counter
    >>> counter = get_audit_failure_counter()
    >>> counter.record_failure("database", "Connection timeout")
    >>> counter.get_failure_count()
    1
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from django.core.cache import cache


logger = logging.getLogger(__name__)


@dataclass
class FailureRecord:
    """
    单次失败记录

    Attributes:
        timestamp: 失败时间戳
        component: 失败组件 (database, validation, repository)
        reason: 失败原因
    """
    timestamp: datetime
    component: str
    reason: str

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "component": self.component,
            "reason": self.reason,
        }


@dataclass
class FailureStats:
    """
    失败统计信息

    Attributes:
        total_count: 总失败次数
        by_component: 按组件分组的失败次数
        recent_failures: 最近的失败记录（最多 10 条）
    """
    total_count: int = 0
    by_component: Dict[str, int] = field(default_factory=dict)
    recent_failures: List[FailureRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_count": self.total_count,
            "by_component": self.by_component,
            "recent_failures": [f.to_dict() for f in self.recent_failures],
        }


class AuditFailureCounter:
    """
    审计失败计数器

    使用 Django cache 存储计数，支持跨进程共享。
    """

    # Cache key
    CACHE_KEY_PREFIX = "audit:failure_counter"

    # 最大保留的最近失败记录数
    MAX_RECENT_FAILURES = 10

    # 默认健康检查阈值（超过此数量返回 WARNING）
    DEFAULT_HEALTH_THRESHOLD = 10

    def __init__(self, cache_backend: Optional[str] = None):
        """
        初始化计数器

        Args:
            cache_backend: 使用的 cache 后端名称，None 表示使用默认
        """
        self._cache = cache if cache_backend is None else cache

    def _get_cache_key(self, suffix: str = "") -> str:
        """获取 cache key"""
        key = self.CACHE_KEY_PREFIX
        if suffix:
            key = f"{key}:{suffix}"
        return key

    def _get_stats(self) -> FailureStats:
        """从 cache 获取统计信息"""
        stats_json = self._cache.get(self._get_cache_key("stats"))
        if stats_json is None:
            return FailureStats()

        # 恢复 FailureStats 对象
        return FailureStats(
            total_count=stats_json.get("total_count", 0),
            by_component=stats_json.get("by_component", {}),
            recent_failures=[
                FailureRecord(
                    timestamp=datetime.fromisoformat(f["timestamp"]),
                    component=f["component"],
                    reason=f["reason"],
                )
                for f in stats_json.get("recent_failures", [])
            ],
        )

    def _save_stats(self, stats: FailureStats) -> None:
        """保存统计信息到 cache"""
        stats_json = stats.to_dict()
        # 设置 1 小时过期时间，避免永久占用
        self._cache.set(self._get_cache_key("stats"), stats_json, timeout=3600)

    def record_failure(
        self,
        component: str,
        reason: str,
        exc_info: Optional[bool] = False,
    ) -> None:
        """
        记录一次失败

        Args:
            component: 失败组件 (database, validation, repository, etc.)
            reason: 失败原因
            exc_info: 是否记录完整的异常堆栈信息
        """
        try:
            stats = self._get_stats()

            # 增加总计数
            stats.total_count += 1

            # 按组件分组计数
            stats.by_component[component] = stats.by_component.get(component, 0) + 1

            # 添加到最近失败记录
            record = FailureRecord(
                timestamp=datetime.now(timezone.utc),
                component=component,
                reason=reason,
            )
            stats.recent_failures.insert(0, record)

            # 限制最近失败记录数量
            if len(stats.recent_failures) > self.MAX_RECENT_FAILURES:
                stats.recent_failures = stats.recent_failures[: self.MAX_RECENT_FAILURES]

            # 保存到 cache
            self._save_stats(stats)

            # 记录日志
            logger.warning(
                f"Audit failure recorded: component={component}, reason={reason}, "
                f"total_count={stats.total_count}"
            )

            if exc_info:
                logger.error(
                    f"Audit failure exception details: component={component}",
                    exc_info=True,
                )

        except Exception as e:
            # 计数器本身失败不应影响业务流程
            logger.error(f"Failed to record audit failure: {e}", exc_info=True)

    def get_failure_count(self) -> int:
        """
        获取总失败次数

        Returns:
            int: 失败次数
        """
        stats = self._get_stats()
        return stats.total_count

    def get_failure_stats(self) -> FailureStats:
        """
        获取完整的失败统计信息

        Returns:
            FailureStats: 统计信息对象
        """
        return self._get_stats()

    def reset(self) -> None:
        """重置计数器"""
        try:
            self._cache.delete(self._get_cache_key("stats"))
            logger.info("Audit failure counter reset")
        except Exception as e:
            logger.error(f"Failed to reset audit failure counter: {e}", exc_info=True)

    def get_health_status(
        self, threshold: Optional[int] = None
    ) -> Dict[str, any]:
        """
        获取健康状态

        Args:
            threshold: 失败次数阈值，超过返回 WARNING，默认为 DEFAULT_HEALTH_THRESHOLD

        Returns:
            dict: 健康状态信息
                {
                    "status": "OK" | "WARNING" | "ERROR",
                    "total_count": int,
                    "threshold": int,
                    "by_component": dict,
                    "recent_failures": list,
                }
        """
        if threshold is None:
            threshold = self.DEFAULT_HEALTH_THRESHOLD

        stats = self._get_stats()

        # 判断状态
        if stats.total_count == 0:
            status = "OK"
        elif stats.total_count < threshold:
            status = "OK"
        elif stats.total_count < threshold * 2:
            status = "WARNING"
        else:
            status = "ERROR"

        return {
            "status": status,
            "total_count": stats.total_count,
            "threshold": threshold,
            "by_component": stats.by_component,
            "recent_failures": [f.to_dict() for f in stats.recent_failures],
        }

    def increment_component_count(self, component: str) -> int:
        """
        增加指定组件的失败计数（快捷方法）

        Args:
            component: 组件名称

        Returns:
            int: 更新后的该组件失败次数
        """
        stats = self._get_stats()
        stats.total_count += 1
        stats.by_component[component] = stats.by_component.get(component, 0) + 1
        self._save_stats(stats)
        return stats.by_component[component]


# 全局单例
_failure_counter: Optional[AuditFailureCounter] = None


def get_audit_failure_counter() -> AuditFailureCounter:
    """
    获取审计失败计数器单例

    Returns:
        AuditFailureCounter: 计数器实例
    """
    global _failure_counter

    if _failure_counter is None:
        _failure_counter = AuditFailureCounter()

    return _failure_counter


def record_audit_failure(
    component: str,
    reason: str,
    exc_info: bool = False,
) -> None:
    """
    记录审计失败（快捷函数）

    Args:
        component: 失败组件
        reason: 失败原因
        exc_info: 是否记录异常堆栈
    """
    counter = get_audit_failure_counter()
    counter.record_failure(component, reason, exc_info)


def get_audit_failure_count() -> int:
    """
    获取审计失败次数（快捷函数）

    Returns:
        int: 失败次数
    """
    counter = get_audit_failure_counter()
    return counter.get_failure_count()


def get_audit_failure_stats() -> FailureStats:
    """
    获取审计失败统计信息（快捷函数）

    Returns:
        FailureStats: 统计信息
    """
    counter = get_audit_failure_counter()
    return counter.get_failure_stats()


def reset_audit_failure_counter() -> None:
    """重置审计失败计数器（快捷函数）"""
    counter = get_audit_failure_counter()
    counter.reset()
