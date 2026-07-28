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
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypedDict

from django.core.cache import cache, caches
from django.core.cache.backends.base import BaseCache

logger = logging.getLogger(__name__)

_COMPONENT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_KNOWN_COMPONENTS = (
    "cache",
    "database",
    "repository",
    "timeout",
    "validation",
    "unknown",
)


class FailureRecordPayload(TypedDict):
    timestamp: str
    component: str
    reason: str


class FailureStatsPayload(TypedDict):
    total_count: int
    by_component: dict[str, int]
    recent_failures: list[FailureRecordPayload]


def _normalize_component(component: object) -> str:
    if not isinstance(component, str):
        return "unknown"
    normalized = component.strip().casefold()
    if _COMPONENT_PATTERN.fullmatch(normalized) is None:
        return "unknown"
    if normalized in _KNOWN_COMPONENTS:
        return normalized
    return "unknown"


def _normalize_reason(reason: object) -> str:
    marker = reason.casefold() if isinstance(reason, str) else ""
    if "timeout" in marker or "timed out" in marker:
        return "timeout"
    if "database" in marker or "postgres" in marker or "sql" in marker:
        return "database_failure"
    if "connection" in marker:
        return "connection_failure"
    if "validation" in marker or "invalid" in marker:
        return "validation_failure"
    if "repository" in marker:
        return "repository_failure"
    return "audit_write_failure"


@dataclass(frozen=True)
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

    def to_dict(self) -> FailureRecordPayload:
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
    by_component: dict[str, int] = field(default_factory=dict)
    recent_failures: list[FailureRecord] = field(default_factory=list)

    def to_dict(self) -> FailureStatsPayload:
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

    def __init__(self, cache_backend: str | None = None) -> None:
        """
        初始化计数器

        Args:
            cache_backend: 使用的 cache 后端名称，None 表示使用默认
        """
        if cache_backend is not None and (
            not isinstance(cache_backend, str) or not cache_backend.strip()
        ):
            raise ValueError("audit_failure_cache_backend_invalid")
        self._cache: BaseCache = cache if cache_backend is None else caches[cache_backend.strip()]
        self._lock = threading.RLock()

    def _get_cache_key(self, suffix: str = "") -> str:
        """获取 cache key"""
        key = self.CACHE_KEY_PREFIX
        if suffix:
            key = f"{key}:{suffix}"
        return key

    def _get_stats(self) -> FailureStats:
        """从 cache 获取统计信息"""
        try:
            raw_stats = self._cache.get(self._get_cache_key("stats"))
        except Exception as exc:
            logger.warning(
                "Audit failure counter cache read failed; exception_type=%s",
                type(exc).__name__,
            )
            return FailureStats()

        legacy = self._parse_stats_payload(raw_stats)
        total_count = self._read_atomic_count(
            self._get_cache_key("total"),
            fallback=legacy.total_count,
        )
        by_component = {
            component: count
            for component in _KNOWN_COMPONENTS
            if (
                count := self._read_atomic_count(
                    self._get_cache_key(f"component:{component}"),
                    fallback=legacy.by_component.get(component, 0),
                )
            )
            > 0
        }
        return FailureStats(
            total_count=total_count,
            by_component=by_component,
            recent_failures=list(legacy.recent_failures),
        )

    def _save_stats(self, stats: FailureStats) -> None:
        """保存统计信息到 cache"""
        stats_json = stats.to_dict()
        # 设置 1 小时过期时间，避免永久占用
        self._cache.set(self._get_cache_key("stats"), stats_json, timeout=3600)

    def _parse_stats_payload(self, payload: object) -> FailureStats:
        if not isinstance(payload, dict):
            return FailureStats()
        raw_total = payload.get("total_count", 0)
        total_count = (
            raw_total
            if isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0
            else 0
        )
        by_component: dict[str, int] = {}
        raw_components = payload.get("by_component", {})
        if isinstance(raw_components, dict):
            for raw_component, raw_count in list(raw_components.items())[:100]:
                component = _normalize_component(raw_component)
                if (
                    (component != "unknown" or raw_component == "unknown")
                    and isinstance(raw_count, int)
                    and not isinstance(raw_count, bool)
                    and raw_count > 0
                ):
                    by_component[component] = raw_count

        recent_failures: list[FailureRecord] = []
        raw_failures = payload.get("recent_failures", [])
        if isinstance(raw_failures, list):
            for raw_failure in raw_failures[: self.MAX_RECENT_FAILURES]:
                if not isinstance(raw_failure, dict):
                    continue
                raw_timestamp = raw_failure.get("timestamp")
                if not isinstance(raw_timestamp, str) or len(raw_timestamp) > 64:
                    continue
                try:
                    timestamp = datetime.fromisoformat(raw_timestamp)
                except ValueError:
                    continue
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    continue
                recent_failures.append(
                    FailureRecord(
                        timestamp=timestamp,
                        component=_normalize_component(raw_failure.get("component")),
                        reason=_normalize_reason(raw_failure.get("reason")),
                    )
                )
        return FailureStats(
            total_count=total_count,
            by_component=by_component,
            recent_failures=recent_failures,
        )

    def _read_atomic_count(self, key: str, *, fallback: int) -> int:
        try:
            value = self._cache.get(key)
        except Exception:
            return fallback
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return fallback

    def _increment_atomic_count(self, key: str, *, fallback: int) -> int:
        try:
            if self._cache.add(key, 1, timeout=3600) is True:
                return 1
            value = self._cache.incr(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
        except Exception as exc:
            logger.warning(
                "Audit failure counter atomic increment failed; exception_type=%s",
                type(exc).__name__,
            )
        return fallback + 1

    def record_failure(
        self,
        component: str,
        reason: str,
        exc_info: bool | None = False,
    ) -> None:
        """
        记录一次失败

        Args:
            component: 失败组件 (database, validation, repository, etc.)
            reason: 失败原因
            exc_info: 是否记录完整的异常堆栈信息
        """
        try:
            normalized_component = _normalize_component(component)
            normalized_reason = _normalize_reason(reason)
            with self._lock:
                stats = self._get_stats()
                stats.total_count = self._increment_atomic_count(
                    self._get_cache_key("total"),
                    fallback=stats.total_count,
                )
                stats.by_component[normalized_component] = self._increment_atomic_count(
                    self._get_cache_key(f"component:{normalized_component}"),
                    fallback=stats.by_component.get(normalized_component, 0),
                )
                stats.recent_failures.insert(
                    0,
                    FailureRecord(
                        timestamp=datetime.now(UTC),
                        component=normalized_component,
                        reason=normalized_reason,
                    ),
                )
                stats.recent_failures = stats.recent_failures[: self.MAX_RECENT_FAILURES]
                self._save_stats(stats)

            # 记录日志
            logger.warning(
                "Audit failure recorded: component=%s, reason=%s, total_count=%s",
                normalized_component,
                normalized_reason,
                stats.total_count,
            )

            if exc_info:
                logger.warning(
                    "Audit failure traceback suppressed: component=%s",
                    normalized_component,
                )

        except Exception as exc:
            # 计数器本身失败不应影响业务流程
            logger.warning(
                "Failed to record audit failure; exception_type=%s",
                type(exc).__name__,
            )

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
            with self._lock:
                self._cache.delete(self._get_cache_key("stats"))
                self._cache.delete_many(
                    [
                        self._get_cache_key("total"),
                        *[
                            self._get_cache_key(f"component:{component}")
                            for component in _KNOWN_COMPONENTS
                        ],
                    ]
                )
            logger.info("Audit failure counter reset")
        except Exception as exc:
            logger.warning(
                "Failed to reset audit failure counter; exception_type=%s",
                type(exc).__name__,
            )

    def get_health_status(self, threshold: int | None = None) -> dict[str, object]:
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
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or not 1 <= threshold <= 1_000_000
        ):
            raise ValueError("audit_failure_threshold_invalid")

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
        normalized_component = _normalize_component(component)
        with self._lock:
            stats = self._get_stats()
            stats.total_count = self._increment_atomic_count(
                self._get_cache_key("total"),
                fallback=stats.total_count,
            )
            component_count = self._increment_atomic_count(
                self._get_cache_key(f"component:{normalized_component}"),
                fallback=stats.by_component.get(normalized_component, 0),
            )
            stats.by_component[normalized_component] = component_count
            self._save_stats(stats)
            return component_count


# 全局单例
_failure_counter: AuditFailureCounter | None = None
_failure_counter_lock = threading.RLock()


def get_audit_failure_counter() -> AuditFailureCounter:
    """
    获取审计失败计数器单例

    Returns:
        AuditFailureCounter: 计数器实例
    """
    global _failure_counter

    with _failure_counter_lock:
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
