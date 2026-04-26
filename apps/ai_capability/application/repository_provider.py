"""Composition helpers for ai_capability application consumers."""

from __future__ import annotations

from apps.ai_capability.infrastructure.providers import (
    DjangoCapabilityRepository,
    DjangoRoutingLogRepository,
    DjangoSyncLogRepository,
    get_capability_execution_support_repository,
)


def get_capability_repository() -> DjangoCapabilityRepository:
    """Return the default capability repository."""

    return DjangoCapabilityRepository()


def get_routing_log_repository() -> DjangoRoutingLogRepository:
    """Return the default routing log repository."""

    return DjangoRoutingLogRepository()


def get_capability_sync_log_repository() -> DjangoSyncLogRepository:
    """Return the default sync log repository."""

    return DjangoSyncLogRepository()


def build_api_capability_collector():
    """Build the internal API capability collector lazily."""

    from apps.ai_capability.infrastructure.collectors.api_collector import (
        ApiCapabilityCollector,
    )

    return ApiCapabilityCollector()


__all__ = [
    "DjangoCapabilityRepository",
    "DjangoRoutingLogRepository",
    "DjangoSyncLogRepository",
    "build_api_capability_collector",
    "get_capability_repository",
    "get_capability_sync_log_repository",
    "get_capability_execution_support_repository",
    "get_routing_log_repository",
]
