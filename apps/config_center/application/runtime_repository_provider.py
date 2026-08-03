"""Composition seam for runtime configuration application services."""

from __future__ import annotations

from apps.config_center.application.capacity_profile import (
    StorageCapacityObservationRepositoryProtocol,
    StorageCapacityObservationService,
)
from apps.config_center.application.runtime_config import (
    RuntimeConfigDefinitionRepositoryPort,
    RuntimeConfigProfileRepositoryPort,
    RuntimeConfigRevisionRepositoryPort,
    RuntimeConfigService,
    RuntimeConfigSnapshotRepositoryPort,
    RuntimeConfigValueRepositoryPort,
    StorageBudgetQueryService,
    StorageBudgetRepositoryPort,
)

_runtime_service: RuntimeConfigService | None = None
_runtime_definition_repository: RuntimeConfigDefinitionRepositoryPort | None = None
_storage_budget_service: StorageBudgetQueryService | None = None
_capacity_observation_service: StorageCapacityObservationService | None = None


def configure_runtime_config_services(
    *,
    definitions: RuntimeConfigDefinitionRepositoryPort,
    profiles: RuntimeConfigProfileRepositoryPort,
    values: RuntimeConfigValueRepositoryPort,
    revisions: RuntimeConfigRevisionRepositoryPort,
    snapshots: RuntimeConfigSnapshotRepositoryPort,
    storage_budget: StorageBudgetRepositoryPort,
    capacity_observations: StorageCapacityObservationRepositoryProtocol,
) -> None:
    """Configure concrete infrastructure repositories at the composition root."""

    global _runtime_service, _runtime_definition_repository
    global _storage_budget_service, _capacity_observation_service
    _runtime_definition_repository = definitions
    _runtime_service = RuntimeConfigService(definitions, profiles, values, revisions, snapshots)
    _storage_budget_service = StorageBudgetQueryService(storage_budget)
    _capacity_observation_service = StorageCapacityObservationService(capacity_observations)


def get_runtime_config_service() -> RuntimeConfigService:
    """Return the configured runtime service."""

    if _runtime_service is None:
        raise RuntimeError("Runtime config services are not configured")
    return _runtime_service


def get_runtime_definition_repository() -> RuntimeConfigDefinitionRepositoryPort:
    """Return the configured definition registry application port."""

    if _runtime_definition_repository is None:
        raise RuntimeError("Runtime config definition repository is not configured")
    return _runtime_definition_repository


def get_storage_budget_query_service() -> StorageBudgetQueryService:
    """Return the configured storage-budget query port."""

    if _storage_budget_service is None:
        raise RuntimeError("Storage budget service is not configured")
    return _storage_budget_service


def get_storage_capacity_observation_service() -> StorageCapacityObservationService:
    """Return the configured capacity-observation application service."""

    if _capacity_observation_service is None:
        raise RuntimeError("Storage capacity observation service is not configured")
    return _capacity_observation_service


__all__ = [
    "configure_runtime_config_services",
    "get_runtime_definition_repository",
    "get_runtime_config_service",
    "get_storage_budget_query_service",
    "get_storage_capacity_observation_service",
]
