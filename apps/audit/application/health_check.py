"""
Audit Module Health Check

审计模块健康检查，确保审计日志系统正常运行。

Features:
1. 检查审计日志写入状态
2. 检查失败计数器状态
3. 检查数据库连接
4. 验证审计表可访问性
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from apps.audit.domain.interfaces import AuditRepositoryProtocol

from .repository_provider import get_audit_failure_counter, get_audit_repository

logger = logging.getLogger(__name__)


class FailureStatsProtocol(Protocol):
    """Failure aggregates required by the health checker."""

    @property
    def total_count(self) -> int: ...

    @property
    def by_component(self) -> Mapping[str, int]: ...


class FailureCounterProtocol(Protocol):
    """Failure counter surface required by the health checker."""

    def get_failure_stats(self) -> FailureStatsProtocol: ...

    def get_failure_count(self) -> int: ...

    def reset(self) -> None: ...


@dataclass(frozen=True)
class HealthCheckResult:
    """
    健康检查结果

    Attributes:
        component: 组件名称
        status: 状态（OK, WARNING, ERROR）
        message: 消息
        details: 详细信息
        checked_at: 检查时间
    """

    component: str
    status: str  # OK, WARNING, ERROR
    message: str
    details: dict[str, Any]
    checked_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == "OK"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "component": self.component,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True)
class AuditHealthReport:
    """
    审计模块健康报告

    Attributes:
        overall_status: 总体状态
        checks: 检查结果列表
        metrics: 审计模块指标
        generated_at: 生成时间
    """

    overall_status: str  # OK, WARNING, ERROR
    checks: list[HealthCheckResult]
    metrics: dict[str, Any]
    generated_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.overall_status == "OK"

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "metrics": self.metrics,
            "generated_at": self.generated_at.isoformat(),
        }


class AuditHealthChecker:
    """
    审计模块健康检查器

    检查审计日志系统的各个组件是否正常运行。

    Example:
        >>> checker = AuditHealthChecker()
        >>> report = checker.check_all()
        >>> print(report.overall_status)
    """

    # 失败阈值配置
    DEFAULT_FAILURE_WARNING_THRESHOLD = 10
    DEFAULT_FAILURE_ERROR_THRESHOLD = 50

    def __init__(
        self,
        warning_threshold: int | None = None,
        error_threshold: int | None = None,
        audit_repo: AuditRepositoryProtocol | None = None,
        failure_counter: FailureCounterProtocol | None = None,
    ) -> None:
        """
        初始化健康检查器

        Args:
            warning_threshold: WARNING 状态阈值（失败次数）
            error_threshold: ERROR 状态阈值（失败次数）
            audit_repo: 审计仓储协议实现
            failure_counter: 失败计数器实现
        """
        self.warning_threshold = (
            self.DEFAULT_FAILURE_WARNING_THRESHOLD
            if warning_threshold is None
            else warning_threshold
        )
        self.error_threshold = (
            self.DEFAULT_FAILURE_ERROR_THRESHOLD if error_threshold is None else error_threshold
        )
        if (
            isinstance(self.warning_threshold, bool)
            or not isinstance(self.warning_threshold, int)
            or self.warning_threshold < 0
        ):
            raise ValueError("warning_threshold must be a non-negative integer")
        if (
            isinstance(self.error_threshold, bool)
            or not isinstance(self.error_threshold, int)
            or self.error_threshold <= self.warning_threshold
        ):
            raise ValueError("error_threshold must be an integer greater than warning_threshold")
        self.audit_repo = audit_repo or get_audit_repository()
        self.failure_counter = failure_counter or get_audit_failure_counter()

    def check_all(self) -> AuditHealthReport:
        """
        执行所有健康检查

        Returns:
            健康报告
        """
        checks = []

        # 1. 检查失败计数器状态
        checks.append(self._check_failure_counter())

        # 2. 检查数据库连接
        checks.append(self._check_database_connection())

        # 3. 检查审计表可访问性
        checks.append(self._check_audit_tables_accessible())

        # 获取审计模块指标
        metrics = self._get_audit_metrics()
        if not metrics.get("available", False):
            checks.append(
                HealthCheckResult(
                    component="audit_metrics",
                    status="ERROR",
                    message="Audit metrics are unavailable",
                    details={"error_type": metrics.get("error_type", "UnknownError")},
                    checked_at=datetime.now(UTC),
                )
            )

        # 计算总体状态
        overall_status = self._calculate_overall_status(checks)

        return AuditHealthReport(
            overall_status=overall_status,
            checks=checks,
            metrics=metrics,
            generated_at=datetime.now(UTC),
        )

    def _check_failure_counter(self) -> HealthCheckResult:
        """
        检查失败计数器状态

        Returns:
            检查结果
        """
        try:
            failure_stats = self.failure_counter.get_failure_stats()
            total_failures = failure_stats.total_count

            # 判断状态
            if total_failures == 0:
                status = "OK"
                message = "No audit failures recorded"
            elif total_failures < self.warning_threshold:
                status = "OK"
                message = f"Audit failures within acceptable range: {total_failures}"
            elif total_failures < self.error_threshold:
                status = "WARNING"
                message = f"High audit failure count: {total_failures}"
            else:
                status = "ERROR"
                message = f"Critical audit failure count: {total_failures}"

            return HealthCheckResult(
                component="audit_failure_counter",
                status=status,
                message=message,
                details={
                    "total_failures": total_failures,
                    "by_component": dict(failure_stats.by_component),
                    "warning_threshold": self.warning_threshold,
                    "error_threshold": self.error_threshold,
                },
                checked_at=datetime.now(UTC),
            )

        except Exception as exc:
            logger.error(
                "Failed to check failure counter: %s",
                type(exc).__name__,
                exc_info=True,
            )
            return HealthCheckResult(
                component="audit_failure_counter",
                status="ERROR",
                message="Failed to check audit failure counter",
                details={"error_type": type(exc).__name__},
                checked_at=datetime.now(UTC),
            )

    def _check_database_connection(self) -> HealthCheckResult:
        """
        检查数据库连接

        Returns:
            检查结果
        """
        try:
            self.audit_repo.get_database_health()

            return HealthCheckResult(
                component="audit_database_connection",
                status="OK",
                message="Database connection is healthy",
                details={"probe": "passed"},
                checked_at=datetime.now(UTC),
            )

        except Exception as exc:
            logger.error(
                "Database connection check failed: %s",
                type(exc).__name__,
                exc_info=True,
            )
            return HealthCheckResult(
                component="audit_database_connection",
                status="ERROR",
                message="Database connection check failed",
                details={"error_type": type(exc).__name__},
                checked_at=datetime.now(UTC),
            )

    def _check_audit_tables_accessible(self) -> HealthCheckResult:
        """
        检查审计表可访问性

        Returns:
            检查结果
        """
        try:
            # 尝试查询审计表
            self.audit_repo.count_operation_logs()

            return HealthCheckResult(
                component="audit_tables_accessible",
                status="OK",
                message="Audit tables are accessible",
                details={"probe": "passed"},
                checked_at=datetime.now(UTC),
            )

        except Exception as exc:
            logger.error(
                "Audit tables accessibility check failed: %s",
                type(exc).__name__,
                exc_info=True,
            )
            return HealthCheckResult(
                component="audit_tables_accessible",
                status="ERROR",
                message="Audit tables are not accessible",
                details={"error_type": type(exc).__name__},
                checked_at=datetime.now(UTC),
            )

    def _calculate_overall_status(self, checks: list[HealthCheckResult]) -> str:
        """
        计算总体状态

        Args:
            checks: 检查结果列表

        Returns:
            总体状态
        """
        has_error = any(c.status == "ERROR" for c in checks)
        has_warning = any(c.status == "WARNING" for c in checks)

        if has_error:
            return "ERROR"
        elif has_warning:
            return "WARNING"
        else:
            return "OK"

    def _get_audit_metrics(self) -> dict[str, Any]:
        """
        获取审计模块指标

        Returns:
            指标字典
        """
        try:
            # 获取基本统计
            total_logs = self.audit_repo.count_operation_logs()

            # 获取失败统计
            failure_stats = self.failure_counter.get_failure_stats()

            return {
                "available": True,
                "total_operation_logs": total_logs,
                "total_failures": failure_stats.total_count,
                "failure_rate": (
                    failure_stats.total_count / (total_logs + failure_stats.total_count)
                    if total_logs + failure_stats.total_count > 0
                    else 0.0
                ),
                "failures_by_component": dict(failure_stats.by_component),
            }

        except Exception as exc:
            logger.error(
                "Failed to get audit metrics: %s",
                type(exc).__name__,
                exc_info=True,
            )
            return {
                "available": False,
                "error_type": type(exc).__name__,
            }


def get_health_checker(
    warning_threshold: int | None = None,
    error_threshold: int | None = None,
) -> AuditHealthChecker:
    """
    获取按本次阈值构建的健康检查器

    Args:
        warning_threshold: WARNING 状态阈值
        error_threshold: ERROR 状态阈值

    Returns:
        健康检查器
    """
    return AuditHealthChecker(
        warning_threshold=warning_threshold,
        error_threshold=error_threshold,
    )


def check_audit_health(
    warning_threshold: int | None = None,
    error_threshold: int | None = None,
) -> AuditHealthReport:
    """
    检查审计模块健康状态

    Args:
        warning_threshold: WARNING 状态阈值
        error_threshold: ERROR 状态阈值

    Returns:
        健康报告
    """
    checker = AuditHealthChecker(
        warning_threshold=warning_threshold,
        error_threshold=error_threshold,
    )
    return checker.check_all()


def get_audit_failure_count() -> int:
    """
    获取审计失败次数（快捷函数）

    Returns:
        int: 失败次数
    """
    counter = get_audit_failure_counter()
    return counter.get_failure_count()


def reset_audit_failure_counter() -> None:
    """重置审计失败计数器（快捷函数）"""
    counter = get_audit_failure_counter()
    counter.reset()
