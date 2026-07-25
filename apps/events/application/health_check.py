"""Operational health checks for the process-wide event bus."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from ..domain.entities import EventType
from ..domain.services import InMemoryEventBus, get_event_bus
from .repository_provider import get_event_store

logger = logging.getLogger(__name__)

_CRITICAL_HANDLER_IDS: tuple[str, ...] = (
    "events.DecisionApprovedHandler",
    "events.DecisionExecutedHandler",
    "events.DecisionExecutionFailedHandler",
)
_CRITICAL_EVENT_TYPES: tuple[EventType, ...] = (
    EventType.DECISION_APPROVED,
    EventType.DECISION_EXECUTED,
    EventType.DECISION_EXECUTION_FAILED,
)


@dataclass(frozen=True)
class HealthCheckResult:
    """One component health result."""

    component: str
    status: str
    message: str
    details: dict[str, object]
    checked_at: datetime

    def is_healthy(self) -> bool:
        """Return whether this component passed."""
        return self.status == "OK"

    def to_dict(self) -> dict[str, object]:
        """Serialize the result for APIs and task monitoring."""
        return {
            "component": self.component,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(frozen=True)
class EventBusHealthReport:
    """Aggregate event bus health report."""

    overall_status: str
    checks: list[HealthCheckResult]
    metrics: dict[str, object]
    generated_at: datetime

    def is_healthy(self) -> bool:
        """Return whether every required component passed."""
        return self.overall_status == "OK"

    def to_dict(self) -> dict[str, object]:
        """Serialize the aggregate report."""
        return {
            "overall_status": self.overall_status,
            "checks": [check.to_dict() for check in self.checks],
            "metrics": self.metrics,
            "generated_at": self.generated_at.isoformat(),
        }


class EventBusHealthChecker:
    """Check bus lifecycle, subscriptions, persistence, and critical handlers."""

    def check_all(self) -> EventBusHealthReport:
        """Execute all operational checks."""
        event_bus = get_event_bus()
        checks = [
            self._check_event_bus_initialization(event_bus),
            self._check_handler_registration(event_bus),
            self._check_event_store_connection(),
            self._check_critical_handlers(event_bus),
        ]
        return EventBusHealthReport(
            overall_status=self._calculate_overall_status(checks),
            checks=checks,
            metrics=self._get_event_bus_metrics(event_bus),
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _check_event_bus_initialization(
        event_bus: InMemoryEventBus,
    ) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        if not event_bus.is_running():
            return HealthCheckResult(
                component="event_bus_initialization",
                status="ERROR",
                message="Event bus is initialized but stopped",
                details={"initialized": True, "started": False},
                checked_at=checked_at,
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
            checked_at=checked_at,
        )

    @staticmethod
    def _check_handler_registration(
        event_bus: InMemoryEventBus,
    ) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        total_handlers = event_bus.get_subscription_count()
        handlers_by_type = {
            event_type.value: count
            for event_type in EventType
            if (count := event_bus.get_subscription_count(event_type)) > 0
        }
        if total_handlers == 0:
            return HealthCheckResult(
                component="handler_registration",
                status="ERROR",
                message="No event handlers are registered",
                details={
                    "total_handlers": 0,
                    "handlers_by_type": handlers_by_type,
                },
                checked_at=checked_at,
            )
        return HealthCheckResult(
            component="handler_registration",
            status="OK",
            message=f"{total_handlers} handlers registered",
            details={
                "total_handlers": total_handlers,
                "handlers_by_type": handlers_by_type,
            },
            checked_at=checked_at,
        )

    @staticmethod
    def _check_event_store_connection() -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        try:
            metrics = get_event_store().get_metrics()
        except Exception as exc:
            return HealthCheckResult(
                component="event_store_connection",
                status="ERROR",
                message=f"Failed to connect to event store: {exc}",
                details={"error": str(exc)},
                checked_at=checked_at,
            )
        return HealthCheckResult(
            component="event_store_connection",
            status="OK",
            message="Event store is accessible",
            details={
                "total_events": metrics.total_events,
                "events_by_type": metrics.events_by_type,
            },
            checked_at=checked_at,
        )

    @staticmethod
    def _check_critical_handlers(
        event_bus: InMemoryEventBus,
    ) -> HealthCheckResult:
        checked_at = datetime.now(UTC)
        registered_handlers = {
            subscription.handler.get_handler_id()
            for event_type in _CRITICAL_EVENT_TYPES
            for subscription in event_bus.get_subscriptions(event_type)
        }
        missing_handlers = [
            handler_id
            for handler_id in _CRITICAL_HANDLER_IDS
            if handler_id not in registered_handlers
        ]
        if missing_handlers:
            return HealthCheckResult(
                component="critical_handlers",
                status="ERROR",
                message=f"Missing {len(missing_handlers)} critical handlers",
                details={
                    "missing_handlers": missing_handlers,
                    "registered_handlers": sorted(registered_handlers),
                },
                checked_at=checked_at,
            )
        return HealthCheckResult(
            component="critical_handlers",
            status="OK",
            message="All critical handlers registered",
            details={
                "critical_handlers": list(_CRITICAL_HANDLER_IDS),
                "registered_count": len(registered_handlers),
            },
            checked_at=checked_at,
        )

    @staticmethod
    def _calculate_overall_status(checks: list[HealthCheckResult]) -> str:
        if any(check.status == "ERROR" for check in checks):
            return "ERROR"
        if any(check.status == "WARNING" for check in checks):
            return "WARNING"
        return "OK"

    @staticmethod
    def _get_event_bus_metrics(event_bus: InMemoryEventBus) -> dict[str, object]:
        metrics = event_bus.get_metrics()
        return {
            "total_published": metrics.total_published,
            "total_processed": metrics.total_processed,
            "total_failed": metrics.total_failed,
            "total_subscribers": metrics.total_subscribers,
            "avg_processing_time_ms": metrics.avg_processing_time_ms,
            "last_event_at": (metrics.last_event_at.isoformat() if metrics.last_event_at else None),
        }


_health_checker: EventBusHealthChecker | None = None
_health_checker_lock = threading.Lock()


def get_health_checker() -> EventBusHealthChecker:
    """Return the process-wide health checker."""
    global _health_checker

    with _health_checker_lock:
        if _health_checker is None:
            _health_checker = EventBusHealthChecker()
        return _health_checker


def check_event_bus_health() -> EventBusHealthReport:
    """Build the current event bus health report."""
    return get_health_checker().check_all()
