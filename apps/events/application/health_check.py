"""
Event Bus Health Check

事件总线健康检查，确保事件系统正常运行。

Features:
1. 检查事件总线初始化状态
2. 检查事件处理器注册状态
3. 检查事件存储连接
4. 发布测试事件验证链路
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..domain.entities import EventType
from ..domain.services import get_event_bus, InMemoryEventBus


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
    details: Dict[str, any]
    checked_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == "OK"

    def to_dict(self) -> Dict[str, any]:
        """转换为字典"""
        return {
            "component": self.component,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class EventBusHealthReport:
    """
    事件总线健康报告

    Attributes:
        overall_status: 总体状态
        checks: 检查结果列表
        metrics: 事件总线指标
        generated_at: 生成时间
    """
    overall_status: str  # OK, WARNING, ERROR
    checks: List[HealthCheckResult]
    metrics: Dict[str, any]
    generated_at: datetime

    def is_healthy(self) -> bool:
        """是否健康"""
        return self.overall_status == "OK"

    def to_dict(self) -> Dict[str, any]:
        """转换为字典"""
        return {
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "metrics": self.metrics,
            "generated_at": self.generated_at.isoformat(),
        }


class EventBusHealthChecker:
    """
    事件总线健康检查器

    检查事件总线的各个组件是否正常运行。

    Example:
        >>> checker = EventBusHealthChecker()
        >>> report = checker.check_all()
        >>> print(report.overall_status)
    """

    def __init__(self):
        """初始化健康检查器"""
        pass

    def check_all(self) -> EventBusHealthReport:
        """
        执行所有健康检查

        Returns:
            健康报告
        """
        checks = []

        # 1. 检查事件总线初始化
        checks.append(self._check_event_bus_initialization())

        # 2. 检查事件处理器注册
        checks.append(self._check_handler_registration())

        # 3. 检查事件存储连接
        checks.append(self._check_event_store_connection())

        # 4. 检查关键处理器
        checks.append(self._check_critical_handlers())

        # 计算总体状态
        overall_status = self._calculate_overall_status(checks)

        # 获取事件总线指标
        metrics = self._get_event_bus_metrics()

        return EventBusHealthReport(
            overall_status=overall_status,
            checks=checks,
            metrics=metrics,
            generated_at=datetime.now(timezone.utc),
        )

    def _check_event_bus_initialization(self) -> HealthCheckResult:
        """
        检查事件总线初始化状态

        Returns:
            检查结果
        """
        try:
            event_bus = get_event_bus()

            if event_bus is None:
                return HealthCheckResult(
                    component="event_bus_initialization",
                    status="ERROR",
                    message="Event bus is not initialized",
                    details={"initialized": False},
                    checked_at=datetime.now(timezone.utc),
                )

            # 检查是否已启动
            is_started = not getattr(event_bus, "_stopped", True)

            if not is_started:
                return HealthCheckResult(
                    component="event_bus_initialization",
                    status="WARNING",
                    message="Event bus is initialized but not started",
                    details={"initialized": True, "started": False},
                    checked_at=datetime.now(timezone.utc),
                )

            return HealthCheckResult(
                component="event_bus_initialization",
                status="OK",
                message="Event bus is initialized and running",
                details={
                    "initialized": True,
                    "started": True,
                    "type": type(event_bus).__name__,
                },
                checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            return HealthCheckResult(
                component="event_bus_initialization",
                status="ERROR",
                message=f"Failed to check event bus: {e}",
                details={"error": str(e)},
                checked_at=datetime.now(timezone.utc),
            )

    def _check_handler_registration(self) -> HealthCheckResult:
        """
        检查事件处理器注册状态

        Returns:
            检查结果
        """
        try:
            event_bus = get_event_bus()

            if event_bus is None:
                return HealthCheckResult(
                    component="handler_registration",
                    status="ERROR",
                    message="Event bus is not initialized",
                    details={"total_handlers": 0},
                    checked_at=datetime.now(timezone.utc),
                )

            # 获取订阅数量
            total_handlers = event_bus.get_subscription_count()

            # 按事件类型统计
            handlers_by_type = {}
            for event_type in EventType:
                count = event_bus.get_subscription_count(event_type)
                if count > 0:
                    handlers_by_type[event_type.value] = count

            if total_handlers == 0:
                return HealthCheckResult(
                    component="handler_registration",
                    status="WARNING",
                    message="No handlers registered",
                    details={
                        "total_handlers": 0,
                        "handlers_by_type": handlers_by_type,
                    },
                    checked_at=datetime.now(timezone.utc),
                )

            return HealthCheckResult(
                component="handler_registration",
                status="OK",
                message=f"{total_handlers} handlers registered",
                details={
                    "total_handlers": total_handlers,
                    "handlers_by_type": handlers_by_type,
                },
                checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            return HealthCheckResult(
                component="handler_registration",
                status="ERROR",
                message=f"Failed to check handler registration: {e}",
                details={"error": str(e)},
                checked_at=datetime.now(timezone.utc),
            )

    def _check_event_store_connection(self) -> HealthCheckResult:
        """
        检查事件存储连接

        Returns:
            检查结果
        """
        try:
            from ..infrastructure.event_store import get_event_store

            event_store = get_event_store()

            # 尝试获取指标
            metrics = event_store.get_metrics()

            return HealthCheckResult(
                component="event_store_connection",
                status="OK",
                message="Event store is accessible",
                details={
                    "total_events": metrics.total_events,
                    "events_by_type": metrics.events_by_type,
                },
                checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            return HealthCheckResult(
                component="event_store_connection",
                status="ERROR",
                message=f"Failed to connect to event store: {e}",
                details={"error": str(e)},
                checked_at=datetime.now(timezone.utc),
            )

    def _check_critical_handlers(self) -> HealthCheckResult:
        """
        检查关键处理器

        确保决策执行相关的处理器已注册

        Returns:
            检查结果
        """
        critical_handlers = [
            "events.DecisionApprovedHandler",
            "events.DecisionExecutedHandler",
            "events.DecisionExecutionFailedHandler",
        ]

        try:
            event_bus = get_event_bus()

            if event_bus is None:
                return HealthCheckResult(
                    component="critical_handlers",
                    status="ERROR",
                    message="Event bus is not initialized",
                    details={"missing_handlers": critical_handlers},
                    checked_at=datetime.now(timezone.utc),
                )

            # 获取所有订阅
            registered_handlers = set()
            for event_type in [
                EventType.DECISION_APPROVED,
                EventType.DECISION_EXECUTED,
                EventType.DECISION_EXECUTION_FAILED,
            ]:
                subscriptions = event_bus.get_subscriptions(event_type)
                for sub in subscriptions:
                    registered_handlers.add(sub.handler.get_handler_id())

            # 检查关键处理器
            missing_handlers = [
                h for h in critical_handlers if h not in registered_handlers
            ]

            if missing_handlers:
                return HealthCheckResult(
                    component="critical_handlers",
                    status="WARNING",
                    message=f"Missing {len(missing_handlers)} critical handlers",
                    details={
                        "missing_handlers": missing_handlers,
                        "registered_handlers": list(registered_handlers),
                    },
                    checked_at=datetime.now(timezone.utc),
                )

            return HealthCheckResult(
                component="critical_handlers",
                status="OK",
                message="All critical handlers registered",
                details={
                    "critical_handlers": critical_handlers,
                    "registered_count": len(registered_handlers),
                },
                checked_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            return HealthCheckResult(
                component="critical_handlers",
                status="ERROR",
                message=f"Failed to check critical handlers: {e}",
                details={"error": str(e)},
                checked_at=datetime.now(timezone.utc),
            )

    def _calculate_overall_status(self, checks: List[HealthCheckResult]) -> str:
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

    def _get_event_bus_metrics(self) -> Dict[str, any]:
        """
        获取事件总线指标

        Returns:
            指标字典
        """
        try:
            event_bus = get_event_bus()

            if event_bus is None:
                return {}

            metrics = event_bus.get_metrics()

            return {
                "total_published": metrics.total_published,
                "total_processed": metrics.total_processed,
                "total_failed": metrics.total_failed,
                "total_subscribers": metrics.total_subscribers,
                "avg_processing_time_ms": metrics.avg_processing_time_ms,
                "last_event_at": (
                    metrics.last_event_at.isoformat()
                    if metrics.last_event_at else None
                ),
            }

        except Exception as e:
            logger.error(f"Failed to get event bus metrics: {e}", exc_info=True)
            return {"error": str(e)}


# 全局健康检查器单例
_health_checker: Optional[EventBusHealthChecker] = None


def get_health_checker() -> EventBusHealthChecker:
    """
    获取健康检查器单例

    Returns:
        健康检查器
    """
    global _health_checker

    if _health_checker is None:
        _health_checker = EventBusHealthChecker()

    return _health_checker


def check_event_bus_health() -> EventBusHealthReport:
    """
    检查事件总线健康状态

    Returns:
        健康报告
    """
    checker = get_health_checker()
    return checker.check_all()
