"""Initialize the process-wide event bus and its subscriptions."""

from __future__ import annotations

import logging
import threading
from typing import Protocol, runtime_checkable

from ..domain.entities import (
    DomainEvent,
    EventBusConfig,
    EventHandler,
    EventSubscription,
    EventType,
)
from ..domain.registry import get_event_subscriber_registry
from ..domain.services import EventBus, InMemoryEventBus, install_event_bus
from .repository_provider import CeleryEventBus, is_celery_available

logger = logging.getLogger(__name__)


@runtime_checkable
class _EventBusAwareHandler(Protocol):
    """Handler boundary for subscribers that publish follow-up events."""

    event_bus: EventBus | None


class EventBusInitializer:
    """Build and install one fully wired event bus per process."""

    def __init__(self) -> None:
        self.event_bus: InMemoryEventBus | None = None
        self.handlers: list[EventHandler] = []
        self._initialization_lock = threading.RLock()

    def initialize(self) -> InMemoryEventBus:
        """Initialize once, failing closed if any required handler cannot be wired."""
        with self._initialization_lock:
            if self.event_bus is not None and self.event_bus.get_subscription_count() > 0:
                self.event_bus.start()
                install_event_bus(self.event_bus)
                return self.event_bus

            event_bus = self._create_event_bus()
            handlers: list[EventHandler] = []
            try:
                self._register_all_handlers(event_bus, handlers)
                event_bus.start()
                install_event_bus(event_bus)
            except Exception:
                event_bus.stop()
                raise

            self.event_bus = event_bus
            self.handlers = handlers
            logger.info("Event bus initialized with %s handlers", len(handlers))
            return event_bus

    @staticmethod
    def _create_event_bus() -> InMemoryEventBus:
        """Create the configured concrete bus without publishing it globally."""
        config = EventBusConfig()
        if is_celery_available():
            logger.debug("Using CeleryEventBus for async event publishing")
            return CeleryEventBus(config)
        logger.debug("Celery not available, using InMemoryEventBus")
        return InMemoryEventBus(config)

    def _register_all_handlers(
        self,
        event_bus: EventBus,
        handlers: list[EventHandler],
    ) -> None:
        """Register registry-owned and internal handlers on one bus."""
        self._register_from_registry(event_bus, handlers)
        self._register_decision_execution_handlers(event_bus, handlers)
        self._register_logging_handler(event_bus, handlers)

    @staticmethod
    def _register_from_registry(
        event_bus: EventBus,
        handlers: list[EventHandler],
    ) -> None:
        """Construct every declared subscriber and propagate wiring failures."""
        subscribers = get_event_subscriber_registry().get_all_subscribers()
        for subscriber in subscribers:
            handler = subscriber.handler_factory()
            if isinstance(handler, _EventBusAwareHandler):
                handler.event_bus = event_bus

            event_bus.subscribe(
                EventSubscription(
                    subscription_id=(
                        f"registry:{subscriber.module_name}:{subscriber.event_type.value}"
                    ),
                    event_type=subscriber.event_type,
                    handler=handler,
                    priority=subscriber.priority,
                )
            )
            handlers.append(handler)
            logger.debug(
                "Registered handler from registry: %s -> %s",
                subscriber.module_name,
                subscriber.event_type.value,
            )

    @staticmethod
    def _register_decision_execution_handlers(
        event_bus: EventBus,
        handlers: list[EventHandler],
    ) -> None:
        """Register required decision execution consistency handlers."""
        from .decision_execution_handlers import (
            DecisionApprovedHandler,
            DecisionExecutedHandler,
            DecisionExecutionFailedHandler,
            DecisionRejectedHandler,
        )

        handler_specs: tuple[tuple[str, EventType, EventHandler], ...] = (
            (
                "decision_approved",
                EventType.DECISION_APPROVED,
                DecisionApprovedHandler(event_bus=event_bus),
            ),
            (
                "decision_executed",
                EventType.DECISION_EXECUTED,
                DecisionExecutedHandler(event_bus=event_bus),
            ),
            (
                "decision_failed",
                EventType.DECISION_EXECUTION_FAILED,
                DecisionExecutionFailedHandler(event_bus=event_bus),
            ),
            (
                "decision_rejected",
                EventType.DECISION_REJECTED,
                DecisionRejectedHandler(event_bus=event_bus),
            ),
        )
        for subscription_id, event_type, handler in handler_specs:
            event_bus.subscribe(
                EventSubscription(
                    subscription_id=subscription_id,
                    event_type=event_type,
                    handler=handler,
                )
            )
            handlers.append(handler)

    @staticmethod
    def _register_logging_handler(
        event_bus: EventBus,
        handlers: list[EventHandler],
    ) -> None:
        """Register the default regime-event audit logger."""
        handler = LoggingEventHandler()
        event_bus.subscribe(
            EventSubscription(
                subscription_id="events_logging",
                event_type=EventType.REGIME_CHANGED,
                handler=handler,
            )
        )
        handlers.append(handler)

    def get_event_bus(self) -> InMemoryEventBus | None:
        """Return the initialized bus without creating it."""
        return self.event_bus

    def get_handlers(self) -> list[EventHandler]:
        """Return a defensive copy of initialized handlers."""
        return self.handlers.copy()

    def shutdown(self) -> None:
        """Stop this initializer's bus."""
        with self._initialization_lock:
            if self.event_bus is None:
                return
            self.event_bus.stop()
            self.event_bus = None
            self.handlers = []
            logger.info("Event bus shut down")


class LoggingEventHandler(EventHandler):
    """Log subscribed domain events."""

    def __init__(self, level: int = logging.INFO) -> None:
        self.level = level

    def can_handle(self, event_type: EventType) -> bool:
        """Accept the event type selected by the subscription."""
        return True

    def handle(self, event: DomainEvent) -> None:
        """Write the event identity and payload to the configured logger."""
        logger.log(
            self.level,
            "Event: %s | ID: %s | Payload: %s",
            event.event_type.value,
            event.event_id,
            event.payload,
        )

    def get_handler_id(self) -> str:
        """Return the stable handler identifier."""
        return "events.LoggingEventHandler"


_event_bus_initializer: EventBusInitializer | None = None
_initializer_lock = threading.Lock()


def get_event_bus_initializer() -> EventBusInitializer:
    """Return the process-wide initializer singleton."""
    global _event_bus_initializer

    with _initializer_lock:
        if _event_bus_initializer is None:
            _event_bus_initializer = EventBusInitializer()
        return _event_bus_initializer


def get_event_bus() -> InMemoryEventBus:
    """Return the initialized process-wide event bus."""
    return initialize_event_bus()


def initialize_event_bus() -> InMemoryEventBus:
    """Initialize and return the process-wide event bus."""
    return get_event_bus_initializer().initialize()
