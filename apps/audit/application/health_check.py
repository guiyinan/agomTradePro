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
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Dict, List, Optional

from ..infrastructure.failure_counter import get_audit_failure_counter
from ..infrastructure.providers import DjangoAuditRepository

logger = logging.getLogger(__name__)


@dataclass
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
    details: dict[str, any]
    checked_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == "OK"

    def to_dict(self) -> dict[str, any]:
        """转换为字典"""
        return {
            "component": self.component,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
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
    metrics: dict[str, any]
    generated_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.overall_status == "OK"

    def to_dict(self) -> dict[str, any]:
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
    ):
        """
        初始化健康检查器

        Args:
            warning_threshold: WARNING 状态阈值（失败次数）
            error_threshold: ERROR 状态阈值（失败次数）
        """
        self.warning_threshold = warning_threshold or self.DEFAULT_FAILURE_WARNING_THRESHOLD
        self.error_threshold = error_threshold or self.DEFAULT_FAILURE_ERROR_THRESHOLD
        self.audit_repo = DjangoAuditRepository()
        self.failure_counter = get_audit_failure_counter()

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

        # 计算总体状态
        overall_status = self._calculate_overall_status(checks)

        # 获取审计模块指标
        metrics = self._get_audit_metrics()

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
                    "by_component": failure_stats.by_component,
                    "recent_failures": [f.to_dict() for f in failure_stats.recent_failures],
                    "warning_threshold": self.warning_threshold,
                    "error_threshold": self.error_threshold,
                },
                checked_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Failed to check failure counter: {e}", exc_info=True)
            return HealthCheckResult(
                component="audit_failure_counter",
                status="ERROR",
                message=f"Failed to check failure counter: {e}",
                details={"error": str(e)},
                checked_at=datetime.now(UTC),
            )

    def _check_database_connection(self) -> HealthCheckResult:
        """
        检查数据库连接

        Returns:
            检查结果
        """
        try:
            from django.db import connection

            # 执行简单查询测试连接
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")

            return HealthCheckResult(
                component="audit_database_connection",
                status="OK",
                message="Database connection is healthy",
                details={
                    "database": connection.settings_dict["NAME"],
                    "engine": connection.settings_dict["ENGINE"],
                },
                checked_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Database connection check failed: {e}", exc_info=True)
            return HealthCheckResult(
                component="audit_database_connection",
                status="ERROR",
                message=f"Database connection failed: {e}",
                details={"error": str(e)},
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
            count = self.audit_repo.count_operation_logs()

            return HealthCheckResult(
                component="audit_tables_accessible",
                status="OK",
                message=f"Audit tables are accessible, {count} records found",
                details={
                    "operation_log_count": count,
                },
                checked_at=datetime.now(UTC),
            )

        except Exception as e:
            logger.error(f"Audit tables accessibility check failed: {e}", exc_info=True)
            return HealthCheckResult(
                component="audit_tables_accessible",
                status="ERROR",
                message=f"Cannot access audit tables: {e}",
                details={"error": str(e)},
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

    def _get_audit_metrics(self) -> dict[str, any]:
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
                "total_operation_logs": total_logs,
                "total_failures": failure_stats.total_count,
                "failure_rate": (
                    failure_stats.total_count / total_logs if total_logs > 0 else 0
                ),
                "failures_by_component": failure_stats.by_component,
            }

        except Exception as e:
            logger.error(f"Failed to get audit metrics: {e}", exc_info=True)
            return {"error": str(e)}


# 全局健康检查器单例
_health_checker: AuditHealthChecker | None = None


def get_health_checker(
    warning_threshold: int | None = None,
    error_threshold: int | None = None,
) -> AuditHealthChecker:
    """
    获取健康检查器单例

    Args:
        warning_threshold: WARNING 状态阈值
        error_threshold: ERROR 状态阈值

    Returns:
        健康检查器
    """
    global _health_checker

    if _health_checker is None:
        _health_checker = AuditHealthChecker(
            warning_threshold=warning_threshold,
            error_threshold=error_threshold,
        )

    return _health_checker


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
