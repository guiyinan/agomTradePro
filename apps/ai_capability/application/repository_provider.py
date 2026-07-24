"""Composition helpers for ai_capability application consumers."""

from __future__ import annotations

from typing import Protocol

from apps.ai_capability.domain.entities import CapabilityDefinition
from apps.ai_capability.infrastructure.confirmation_tokens import DjangoConfirmationCodec
from apps.ai_capability.infrastructure.providers import (
    DjangoCapabilityRepository,
    DjangoRoutingLogRepository,
    DjangoSyncLogRepository,
    get_capability_execution_support_repository,
)


class ApiCapabilityCollectorProtocol(Protocol):
    """Read contract exposed by the API capability collector factory."""

    def collect(self) -> list[CapabilityDefinition]:
        """Collect normalized internal API capabilities."""

        ...


def get_capability_repository() -> DjangoCapabilityRepository:
    """Return the default capability repository."""

    return DjangoCapabilityRepository()


def get_routing_log_repository() -> DjangoRoutingLogRepository:
    """Return the default routing log repository."""

    return DjangoRoutingLogRepository()


def get_capability_sync_log_repository() -> DjangoSyncLogRepository:
    """Return the default sync log repository."""

    return DjangoSyncLogRepository()


def build_api_capability_collector() -> ApiCapabilityCollectorProtocol:
    """Build the internal API capability collector lazily."""

    from apps.ai_capability.infrastructure.collectors.api_collector import (
        ApiCapabilityCollector,
    )

    return ApiCapabilityCollector()


def get_confirmation_codec() -> DjangoConfirmationCodec:
    """Return the signed confirmation codec."""

    return DjangoConfirmationCodec()


__all__ = [
    "DjangoCapabilityRepository",
    "DjangoRoutingLogRepository",
    "DjangoSyncLogRepository",
    "build_api_capability_collector",
    "get_capability_repository",
    "get_capability_sync_log_repository",
    "get_capability_execution_support_repository",
    "get_confirmation_codec",
    "get_routing_log_repository",
]
