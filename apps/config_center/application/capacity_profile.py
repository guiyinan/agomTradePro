"""Application ports for recording and reading capacity observations."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from apps.config_center.domain.runtime_config import StorageCapacityObservation

from .storage_budget import StorageBudgetQueryPort, StoragePressureGuard


class StorageCapacityProfileBlockedError(RuntimeError):
    """Raised when capacity evidence cannot be collected safely."""


class StorageCapacityObserverProtocol(Protocol):
    """Read-only infrastructure port for host and database capacity metrics."""

    def collect(
        self,
        *,
        environment: str,
        policy_key: str,
        configured_capacity_bytes: int,
        source: str,
    ) -> StorageCapacityObservation: ...


class StorageCapacityObservationRepositoryProtocol(Protocol):
    """Persistence port for filesystem/database capacity evidence."""

    def save(self, observation: StorageCapacityObservation) -> StorageCapacityObservation: ...
    def get_latest(self, environment: str) -> StorageCapacityObservation | None: ...
    def list_recent(
        self,
        environment: str,
        *,
        limit: int = 30,
    ) -> list[StorageCapacityObservation]: ...


class RecordStorageCapacityObservationUseCase:
    """Persist an observed capacity snapshot without ORM knowledge."""

    def __init__(self, repository: StorageCapacityObservationRepositoryProtocol) -> None:
        self._repository = repository

    def execute(self, observation: StorageCapacityObservation) -> StorageCapacityObservation:
        """Validate and persist one immutable-ish capacity observation."""

        return self._repository.save(observation)


class StorageCapacityObservationService:
    """Application facade for capacity evidence consumers."""

    def __init__(self, repository: StorageCapacityObservationRepositoryProtocol) -> None:
        self._repository = repository

    def record(self, observation: StorageCapacityObservation) -> StorageCapacityObservation:
        """Record one validated observation."""

        return RecordStorageCapacityObservationUseCase(self._repository).execute(observation)

    def get_latest(self, environment: str) -> StorageCapacityObservation | None:
        """Return the latest observation for an environment."""

        return self._repository.get_latest(environment)

    def list_recent(
        self,
        environment: str,
        *,
        limit: int = 30,
    ) -> list[StorageCapacityObservation]:
        """Return bounded observation history."""

        return self._repository.list_recent(environment, limit=limit)


class StorageCapacityProfileService:
    """Collect, evaluate and persist one policy-bound capacity observation."""

    def __init__(
        self,
        policy_port: StorageBudgetQueryPort,
        observer: StorageCapacityObserverProtocol,
        repository: StorageCapacityObservationRepositoryProtocol,
    ) -> None:
        self._policy_port = policy_port
        self._observer = observer
        self._repository = repository

    def collect_and_record(
        self,
        *,
        environment: str,
        source: str = "runtime-observer",
    ) -> StorageCapacityObservation:
        """Persist one observation or fail closed without an active policy."""

        normalized_environment = str(environment or "").strip()
        normalized_source = str(source or "").strip()
        if not normalized_environment:
            raise ValueError("environment cannot be empty")
        if not normalized_source:
            raise ValueError("source cannot be empty")

        policy = self._policy_port.get_active()
        if policy is None or not policy.active:
            raise StorageCapacityProfileBlockedError("storage_budget_policy_missing_or_inactive")
        base = self._observer.collect(
            environment=normalized_environment,
            policy_key=policy.policy_key,
            configured_capacity_bytes=policy.configured_capacity_bytes,
            source=normalized_source,
        )
        pressure = StoragePressureGuard(self._policy_port).evaluate(
            used_bytes=base.filesystem_used_bytes,
            actual_capacity_bytes=base.filesystem_total_bytes,
        )
        if pressure.state.value == "blocked":
            raise StorageCapacityProfileBlockedError(pressure.reason)
        return self._repository.save(
            replace(
                base,
                effective_capacity_bytes=pressure.effective_capacity_bytes,
                usage_ratio=pressure.usage_ratio,
                pressure_state=pressure.state.value,
            )
        )


__all__ = [
    "RecordStorageCapacityObservationUseCase",
    "StorageCapacityObserverProtocol",
    "StorageCapacityObservationService",
    "StorageCapacityObservationRepositoryProtocol",
    "StorageCapacityProfileBlockedError",
    "StorageCapacityProfileService",
]
