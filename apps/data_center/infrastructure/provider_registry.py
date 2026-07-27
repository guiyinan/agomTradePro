"""Canonical runtime registry for Data Center providers.

This is the single owner for provider construction, configured lookup,
capability routing, failover, circuit breaking, and runtime health state.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar, cast

from apps.data_center.domain.entities import ProviderConfig, ProviderHealthSnapshot
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderProtocol,
    UnifiedDataProviderProtocol,
)
from apps.data_center.infrastructure.provider_adapters import build_unified_provider_adapter

T = TypeVar("T")
ProviderBuilder = Callable[[ProviderConfig], UnifiedDataProviderProtocol]

logger = logging.getLogger(__name__)

_CIRCUIT_OPEN_THRESHOLD = 5
_CIRCUIT_OPEN_DURATION_SEC = 300
_PROVIDER_BUILD_EXCEPTIONS = (LookupError, RuntimeError, TypeError, ValueError)


def _is_empty_list(value: object) -> bool:
    """Return whether a provider result is a valid but empty collection."""

    return isinstance(value, list) and not value


class _ProviderState:
    """Runtime state for one provider and capability slot."""

    def __init__(
        self,
        provider: ProviderProtocol,
        priority: int,
        capability: DataCapability,
    ) -> None:
        self.provider = provider
        self.priority = priority
        self.capability = capability
        self.consecutive_failures = 0
        self.last_success_at: datetime | None = None
        self.circuit_open_until: float | None = None
        self.total_calls = 0
        self.total_failures = 0
        self.total_latency_ms = 0.0

    @property
    def health(self) -> ProviderHealthStatus:
        if self.circuit_open_until and time.monotonic() < self.circuit_open_until:
            return ProviderHealthStatus.CIRCUIT_OPEN
        if self.consecutive_failures > 0:
            return ProviderHealthStatus.DEGRADED
        return ProviderHealthStatus.HEALTHY

    @property
    def is_available(self) -> bool:
        if self.circuit_open_until is None:
            return True
        return time.monotonic() >= self.circuit_open_until

    def record_success(self, latency_ms: float) -> None:
        self.consecutive_failures = 0
        self.last_success_at = datetime.now(UTC)
        self.circuit_open_until = None
        self.total_calls += 1
        self.total_latency_ms += latency_ms

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.total_calls += 1
        self.total_failures += 1
        if self.consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
            self.circuit_open_until = time.monotonic() + _CIRCUIT_OPEN_DURATION_SEC
            logger.warning(
                "Provider %s circuit-opened for capability %s "
                "(consecutive_failures=%d); resumes in %ds",
                self.provider.provider_name(),
                self.capability.value,
                self.consecutive_failures,
                _CIRCUIT_OPEN_DURATION_SEC,
            )

    def to_snapshot(self) -> ProviderHealthSnapshot:
        average_latency: float | None = None
        successful_calls = self.total_calls - self.total_failures
        if successful_calls > 0:
            average_latency = self.total_latency_ms / successful_calls
        return ProviderHealthSnapshot(
            provider_name=self.provider.provider_name(),
            capability=self.capability,
            status=self.health,
            consecutive_failures=self.consecutive_failures,
            last_success_at=self.last_success_at,
            avg_latency_ms=average_latency,
        )


class ProviderRegistry:
    """Registry of real configured providers and their runtime health."""

    def __init__(self, *, builder: ProviderBuilder = build_unified_provider_adapter) -> None:
        self._builder = builder
        self._registry: dict[DataCapability, list[_ProviderState]] = {}
        self._providers_by_id: dict[int, UnifiedDataProviderProtocol] = {}
        self._providers_by_name: dict[str, UnifiedDataProviderProtocol] = {}

    @classmethod
    def from_repository(
        cls,
        repository: ProviderConfigRepositoryProtocol,
        *,
        builder: ProviderBuilder = build_unified_provider_adapter,
    ) -> ProviderRegistry:
        """Build a registry from active provider configurations."""
        registry = cls(builder=builder)
        registry.refresh_from_repository(repository)
        return registry

    def refresh_from_repository(
        self,
        repository: ProviderConfigRepositoryProtocol,
    ) -> None:
        """Stage active providers and replace runtime state only after a viable build."""

        configs = repository.list_active()
        staged = ProviderRegistry(builder=self._builder)
        built_count = 0
        for config in configs:
            try:
                provider = self._builder(config)
            except _PROVIDER_BUILD_EXCEPTIONS as exc:
                logger.warning(
                    "Failed to build Data Center provider %s (%s): %s",
                    config.name,
                    config.source_type,
                    type(exc).__name__,
                )
                continue
            staged.register(
                provider,
                priority=config.priority,
                provider_id=config.id,
            )
            built_count += 1

        if configs and built_count == 0:
            raise RuntimeError("No active Data Center provider could be built")

        self._registry = staged._registry
        self._providers_by_id = staged._providers_by_id
        self._providers_by_name = staged._providers_by_name

    def clear(self) -> None:
        """Clear configured providers and all accumulated health state."""
        self._registry.clear()
        self._providers_by_id.clear()
        self._providers_by_name.clear()

    def register(
        self,
        provider: ProviderProtocol,
        priority: int = 100,
        *,
        provider_id: int | None = None,
    ) -> None:
        """Register one provider for every capability it supports."""
        if provider_id is not None:
            unified_provider = cast(UnifiedDataProviderProtocol, provider)
            self._providers_by_id[provider_id] = unified_provider
            self._providers_by_name[provider.provider_name()] = unified_provider

        for capability in DataCapability:
            if not provider.supports(capability):
                continue
            state = _ProviderState(provider, priority, capability)
            bucket = self._registry.setdefault(capability, [])
            bucket.append(state)
            bucket.sort(key=lambda item: item.priority)
            logger.info(
                "Registered provider '%s' for capability '%s' (priority=%d)",
                provider.provider_name(),
                capability.value,
                priority,
            )

    def get_by_id(self, provider_id: int) -> UnifiedDataProviderProtocol | None:
        """Return one configured provider by persistent configuration ID."""
        return self._providers_by_id.get(provider_id)

    def get_by_name(self, provider_name: str) -> UnifiedDataProviderProtocol | None:
        """Return one configured provider by its configured name."""
        return self._providers_by_name.get(provider_name)

    def get_provider(self, capability: DataCapability) -> ProviderProtocol | None:
        """Return the highest-priority available provider for a capability."""
        for state in self._registry.get(capability, []):
            if state.is_available:
                return state.provider
        return None

    def get_providers(self, capability: DataCapability) -> list[ProviderProtocol]:
        """Return available providers in priority order."""
        return [
            state.provider for state in self._registry.get(capability, []) if state.is_available
        ]

    def call_with_failover(
        self,
        capability: DataCapability,
        fn: Callable[[ProviderProtocol], T],
    ) -> T | None:
        """Call available providers in priority order until one succeeds."""
        for state in self._registry.get(capability, []):
            if not state.is_available:
                continue
            provider = state.provider
            started = time.monotonic()
            try:
                result = fn(provider)
            except Exception as exc:
                state.record_failure()
                logger.warning(
                    "Provider '%s' raised %s for '%s'; trying next",
                    provider.provider_name(),
                    type(exc).__name__,
                    capability.value,
                )
                continue
            latency_ms = (time.monotonic() - started) * 1000
            if result is None:
                state.record_failure()
                logger.info(
                    "Provider '%s' violated the '%s' result contract; trying next",
                    provider.provider_name(),
                    capability.value,
                )
                continue
            if _is_empty_list(result):
                state.record_success(latency_ms)
                logger.info(
                    "Provider '%s' returned no data for '%s'; trying next",
                    provider.provider_name(),
                    capability.value,
                )
                continue
            state.record_success(latency_ms)
            return result
        logger.error("All providers failed for capability '%s'", capability.value)
        return None

    def record_success(
        self,
        provider_name: str,
        capability: DataCapability,
        latency_ms: float,
    ) -> None:
        """Record a successful provider call."""
        state = self._find_state(provider_name, capability)
        if state is not None:
            state.record_success(latency_ms)

    def record_failure(self, provider_name: str, capability: DataCapability) -> None:
        """Record a failed provider call."""
        state = self._find_state(provider_name, capability)
        if state is not None:
            state.record_failure()

    def get_all_statuses(self) -> list[ProviderHealthSnapshot]:
        """Return health snapshots for every provider-capability slot."""
        return [state.to_snapshot() for states in self._registry.values() for state in states]

    def _find_state(
        self,
        provider_name: str,
        capability: DataCapability,
    ) -> _ProviderState | None:
        for state in self._registry.get(capability, []):
            if state.provider.provider_name() == provider_name:
                return state
        return None


__all__ = [
    "ProviderRegistry",
    "_CIRCUIT_OPEN_THRESHOLD",
]
