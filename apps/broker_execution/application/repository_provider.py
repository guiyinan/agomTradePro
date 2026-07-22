"""Composition-root provider for broker-execution repositories."""

from __future__ import annotations

from collections.abc import Callable

from .ports import BrokerExecutionRepositoryProtocol

_repository_factory: Callable[[], BrokerExecutionRepositoryProtocol] | None = None


def configure_broker_execution_repository(
    factory: Callable[[], BrokerExecutionRepositoryProtocol],
) -> None:
    """Configure the default broker-execution repository factory."""

    global _repository_factory
    _repository_factory = factory


def get_broker_execution_repository() -> BrokerExecutionRepositoryProtocol:
    """Return the configured broker-execution repository."""

    if _repository_factory is None:
        raise RuntimeError("Broker execution repository is not configured")
    return _repository_factory()
