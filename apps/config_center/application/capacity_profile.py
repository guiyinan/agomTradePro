"""Application ports for recording and reading capacity observations."""

from __future__ import annotations

from typing import Protocol

from apps.config_center.domain.runtime_config import StorageCapacityObservation


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


__all__ = [
    "RecordStorageCapacityObservationUseCase",
    "StorageCapacityObservationService",
    "StorageCapacityObservationRepositoryProtocol",
]
