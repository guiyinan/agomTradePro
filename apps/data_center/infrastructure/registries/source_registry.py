"""
Data Center — Unified Source Registry

Manages all data-provider adapters across the eight data domains.
Supports priority ordering, automatic failover, circuit-breaker, and
health-state queries.

Canonical registry owned by data_center.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from apps.data_center.domain.entities import ProviderHealthSnapshot
from apps.data_center.domain.enums import DataCapability, ProviderHealthStatus
from apps.data_center.domain.protocols import ProviderProtocol

T = TypeVar("T")

logger = logging.getLogger(__name__)

# Consecutive-failure count that triggers a circuit-open state
_CIRCUIT_OPEN_THRESHOLD = 5
# Duration (seconds) a circuit remains open before attempting recovery
_CIRCUIT_OPEN_DURATION_SEC = 300


class _ProviderState:
    """Runtime state for one provider × capability slot."""

    def __init__(
        self,
        provider: ProviderProtocol,
        priority: int,
        capability: DataCapability,
    ) -> None:
        self.provider = provider
        self.priority = priority
        self.capability = capability
        self.consecutive_failures: int = 0
        self.last_success_at: datetime | None = None
        self.circuit_open_until: float | None = None   # monotonic timestamp
        self.total_calls: int = 0
        self.total_failures: int = 0
        self.total_latency_ms: float = 0.0

    @property
    def health(self) -> ProviderHealthStatus:
        if self.circuit_open_until and time.monotonic() < self.circuit_open_until:
            return ProviderHealthStatus.CIRCUIT_OPEN
        if self.consecutive_failures > 0:
            return ProviderHealthStatus.DEGRADED
        return ProviderHealthStatus.HEALTHY

    @property
    def is_available(self) -> bool:
        """True if the provider is not in an active circuit-open state."""
        if self.circuit_open_until is None:
            return True
        return time.monotonic() >= self.circuit_open_until

    def record_success(self, latency_ms: float) -> None:
        self.consecutive_failures = 0
        self.last_success_at = datetime.now(timezone.utc)
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
        avg_latency: float | None = None
        success_calls = self.total_calls - self.total_failures
        if success_calls > 0:
            avg_latency = self.total_latency_ms / success_calls
        return ProviderHealthSnapshot(
            provider_name=self.provider.provider_name(),
            capability=self.capability,
            status=self.health,
            consecutive_failures=self.consecutive_failures,
            last_success_at=self.last_success_at,
            avg_latency_ms=avg_latency,
        )


class SourceRegistry:
    """Unified data-source registry for all eight data domains.

    Usage::

        registry = SourceRegistry()
        registry.register(tushare_provider, priority=10)
        registry.register(akshare_provider, priority=20)

        provider = registry.get_provider(DataCapability.MACRO)
        result = registry.call_with_failover(DataCapability.HISTORICAL_PRICE, fetch_fn)
    """

    def __init__(self) -> None:
        # capability → sorted list of _ProviderState (ascending priority)
        self._registry: dict[DataCapability, list[_ProviderState]] = {}

    def register(
        self,
        provider: ProviderProtocol,
        priority: int = 100,
    ) -> None:
        """Register a provider for every capability it declares support for.

        Args:
            provider: Must implement ProviderProtocol (provider_name + supports).
            priority: Lower value = higher precedence in dispatch.
        """
        for cap in DataCapability:
            if provider.supports(cap):
                state = _ProviderState(provider, priority, cap)
                bucket = self._registry.setdefault(cap, [])
                bucket.append(state)
                bucket.sort(key=lambda s: s.priority)
                logger.info(
                    "Registered provider '%s' for capability '%s' (priority=%d)",
                    provider.provider_name(),
                    cap.value,
                    priority,
                )

    def get_provider(
        self, capability: DataCapability
    ) -> ProviderProtocol | None:
        """Return the highest-priority available provider for *capability*."""
        for state in self._registry.get(capability, []):
            if state.is_available:
                return state.provider
        return None

    def get_providers(
        self, capability: DataCapability
    ) -> list[ProviderProtocol]:
        """Return all available providers for *capability*, priority-ordered."""
        return [
            s.provider
            for s in self._registry.get(capability, [])
            if s.is_available
        ]

    def call_with_failover(
        self,
        capability: DataCapability,
        fn: Callable[[ProviderProtocol], T],
    ) -> T | None:
        """Invoke *fn* on each available provider until one succeeds.

        A call is considered successful when *fn* returns a non-None,
        non-empty-list value.  Every success / failure is recorded in the
        circuit-breaker state automatically.

        Args:
            capability: Required data capability.
            fn: Callable that receives a provider and returns a result.

        Returns:
            The first successful result, or None if all providers fail.
        """
        for state in self._registry.get(capability, []):
            if not state.is_available:
                continue
            provider = state.provider
            t0 = time.monotonic()
            try:
                result = fn(provider)
                if result is None or (isinstance(result, list) and len(result) == 0):
                    state.record_failure()
                    logger.info(
                        "Provider '%s' returned empty result for '%s'; trying next",
                        provider.provider_name(),
                        capability.value,
                    )
                    continue
                state.record_success((time.monotonic() - t0) * 1000)
                return result
            except Exception:
                state.record_failure()
                logger.warning(
                    "Provider '%s' raised an exception for '%s'; trying next",
                    provider.provider_name(),
                    capability.value,
                    exc_info=True,
                )
        logger.error("All providers failed for capability '%s'", capability.value)
        return None

    def record_success(
        self,
        provider_name: str,
        capability: DataCapability,
        latency_ms: float,
    ) -> None:
        """Manually record a successful call (used by callers that manage
        their own try/except around call_with_failover)."""
        state = self._find_state(provider_name, capability)
        if state:
            state.record_success(latency_ms)

    def record_failure(
        self, provider_name: str, capability: DataCapability
    ) -> None:
        """Manually record a failed call."""
        state = self._find_state(provider_name, capability)
        if state:
            state.record_failure()

    def get_all_statuses(self) -> list[ProviderHealthSnapshot]:
        """Return health snapshots for every registered provider × capability."""
        snapshots: list[ProviderHealthSnapshot] = []
        for states in self._registry.values():
            for state in states:
                snapshots.append(state.to_snapshot())
        return snapshots

    def _find_state(
        self, provider_name: str, capability: DataCapability
    ) -> _ProviderState | None:
        for state in self._registry.get(capability, []):
            if state.provider.provider_name() == provider_name:
                return state
        return None
